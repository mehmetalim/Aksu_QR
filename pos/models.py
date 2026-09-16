from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify

# Django slugify'ı 'ı' ve 'ğ' gibi harfleri tamamen atar
# ("Çıtır Börek Tabağı" -> "ctr-borek-tabag"). Önce harf çevirimi yapıyoruz.
TR_MAP = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosucgiosu')


def pos_slug(value, fallback='urun'):
    """POS kurallarına uyan, Türkçe adlardan okunabilir bir kod üretir."""
    return slugify(str(value).translate(TR_MAP))[:50].strip('-') or fallback


# POS (aksu-sistem) store.cjs saveProducts() ile birebir aynı kural.
# Buna uymayan bir kimlik POS'ta "Ürün kimliği geçersiz." hatası verir.
POS_ID_VALIDATOR = RegexValidator(
    r'^[a-zA-Z0-9_-]{1,60}$',
    'Yalnızca İngilizce harf, rakam, alt çizgi ve tire kullanın (en fazla 60 karakter). '
    'Windows POS bu biçimi zorunlu tutar.',
)


class Device(models.Model):
    device_id = models.CharField(max_length=80, unique=True, verbose_name='Cihaz Kimliği')
    name = models.CharField(max_length=100, default='POS', verbose_name='Cihaz Adı')
    is_active = models.BooleanField(default=True, verbose_name='Aktif')
    registered_at = models.DateTimeField(auto_now_add=True, verbose_name='Kayıt Tarihi')
    last_sync_at = models.DateTimeField(null=True, blank=True, verbose_name='Son Senkronizasyon')

    class Meta:
        verbose_name = 'Cihaz'
        verbose_name_plural = 'Cihazlar'

    def __str__(self):
        return f'{self.name} ({self.device_id[:12]}…)'


class Category(models.Model):
    category_id = models.CharField(
        max_length=60, unique=True, verbose_name='Kategori Kodu',
        validators=[POS_ID_VALIDATOR],
    )
    name = models.CharField(max_length=160, verbose_name='Kategori Adı')
    icon = models.CharField(max_length=8, blank=True, verbose_name='Simge')
    display_order = models.IntegerField(default=0, verbose_name='Sıra')

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name = 'Kategori'
        verbose_name_plural = 'Kategoriler'

    def __str__(self):
        return self.name


class Product(models.Model):
    product_id = models.CharField(
        max_length=60, unique=True, verbose_name='Ürün Kodu',
        validators=[POS_ID_VALIDATOR],
        help_text='Boş bırakırsanız ürün adından otomatik üretilir. Sonradan değiştirilemez.',
    )
    name = models.CharField(max_length=160, verbose_name='Ürün Adı')
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        verbose_name='Kategori', related_name='products'
    )
    price = models.IntegerField(verbose_name='Fiyat (kuruş)')
    active = models.BooleanField(default=True, verbose_name='Satışta')
    description = models.TextField(blank=True, verbose_name='Açıklama')
    image = models.CharField(max_length=200, blank=True, verbose_name='Görsel yolu')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__display_order', 'name']
        verbose_name = 'Ürün'
        verbose_name_plural = 'Ürünler'

    def __str__(self):
        return f'{self.name} — {self.price / 100:.2f} TL'

    @property
    def price_tl(self):
        return self.price / 100


class CatalogVersion(models.Model):
    SOURCE_ADMIN = 'admin'
    SOURCE_POS = 'pos'

    version = models.IntegerField(unique=True, verbose_name='Sürüm')
    source = models.CharField(
        max_length=10,
        choices=[(SOURCE_ADMIN, 'Django Admin'), (SOURCE_POS, 'Windows POS')],
        default=SOURCE_ADMIN,
        verbose_name='Kaynak'
    )
    published_at = models.DateTimeField(auto_now_add=True, verbose_name='Yayım Tarihi')
    snapshot = models.JSONField(verbose_name='Katalog Anlık Görüntüsü')

    class Meta:
        ordering = ['-version']
        get_latest_by = 'version'
        verbose_name = 'Katalog Sürümü'
        verbose_name_plural = 'Katalog Sürümleri'

    def __str__(self):
        return f'v{self.version} — {self.get_source_display()} ({self.published_at.strftime("%d.%m.%Y %H:%M")})'


class SyncEvent(models.Model):
    KINDS = [
        ('catalog', 'Katalog'), ('order', 'Sipariş'), ('payment', 'Ödeme'),
        ('void', 'İptal'), ('cash', 'Kasa Hareketi'),
        ('day-close', 'Gün Sonu'), ('security', 'Güvenlik'),
    ]

    event_id = models.CharField(max_length=80, unique=True, verbose_name='Olay Kimliği')
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='Cihaz')
    seq = models.IntegerField(verbose_name='Sıra No')
    kind = models.CharField(max_length=30, choices=KINDS, verbose_name='Tür')
    occurred_at = models.DateTimeField(verbose_name='Oluşma Zamanı')
    received_at = models.DateTimeField(auto_now_add=True, verbose_name='Alınma Zamanı')
    payload = models.JSONField(default=dict, verbose_name='İçerik')

    class Meta:
        unique_together = [('device', 'seq')]
        ordering = ['device', 'seq']
        verbose_name = 'Senkronizasyon Olayı'
        verbose_name_plural = 'Senkronizasyon Olayları'

    def __str__(self):
        return f'{self.get_kind_display()} #{self.seq} — {self.device}'


class Order(models.Model):
    order_id = models.CharField(max_length=80, unique=True, verbose_name='Sipariş Kimliği')
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='Cihaz')
    table_id = models.CharField(max_length=20, verbose_name='Masa')
    status = models.CharField(max_length=20, verbose_name='Durum')
    opened_at = models.DateTimeField(verbose_name='Açılış Zamanı')
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name='Kapanış Zamanı')
    body = models.JSONField(verbose_name='Sipariş Verisi')
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-opened_at']
        verbose_name = 'Sipariş'
        verbose_name_plural = 'Siparişler'

    def __str__(self):
        return f'Masa {self.table_id} — {self.status} ({self.opened_at.strftime("%d.%m.%Y")})'


class Payment(models.Model):
    METHODS = [
        ('cash', 'Nakit'), ('card', 'Kart'),
        ('meal', 'Yemek Kartı'), ('gift', 'İkram'),
    ]

    payment_id = models.CharField(max_length=80, unique=True, verbose_name='Ödeme Kimliği')
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='Cihaz')
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments', verbose_name='Sipariş'
    )
    shift_id = models.CharField(max_length=80, verbose_name='Vardiya')
    method = models.CharField(max_length=10, choices=METHODS, verbose_name='Yöntem')
    total = models.IntegerField(verbose_name='Tutar (kuruş)')
    gift = models.IntegerField(default=0, verbose_name='İkram Tutarı (kuruş)')
    occurred_at = models.DateTimeField(verbose_name='Zaman')
    body = models.JSONField(verbose_name='Ödeme Verisi')

    class Meta:
        ordering = ['-occurred_at']
        verbose_name = 'Ödeme'
        verbose_name_plural = 'Ödemeler'

    def __str__(self):
        return f'{self.get_method_display()} — {self.total / 100:.2f} TL ({self.occurred_at.strftime("%d.%m.%Y")})'


class CashMove(models.Model):
    move_id = models.CharField(max_length=80, unique=True, verbose_name='Hareket Kimliği')
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='Cihaz')
    shift_id = models.CharField(max_length=80, verbose_name='Vardiya')
    amount = models.IntegerField(verbose_name='Tutar (kuruş)')
    reason = models.CharField(max_length=300, verbose_name='Açıklama')
    occurred_at = models.DateTimeField(verbose_name='Zaman')

    class Meta:
        ordering = ['-occurred_at']
        verbose_name = 'Kasa Hareketi'
        verbose_name_plural = 'Kasa Hareketleri'

    def __str__(self):
        sign = '+' if self.amount > 0 else ''
        return f'{sign}{self.amount / 100:.2f} TL — {self.reason}'


class Shift(models.Model):
    shift_id = models.CharField(max_length=80, unique=True, verbose_name='Vardiya Kimliği')
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='Cihaz')
    opened_at = models.DateTimeField(verbose_name='Açılış')
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name='Kapanış')
    opening_cash = models.IntegerField(default=0, verbose_name='Açılış Nakdi (kuruş)')
    revenue = models.IntegerField(default=0, verbose_name='Ciro (kuruş)')
    totals = models.JSONField(default=dict, verbose_name='Toplamlar')
    body = models.JSONField(default=dict, verbose_name='Tam Rapor')

    class Meta:
        ordering = ['-closed_at']
        verbose_name = 'Vardiya'
        verbose_name_plural = 'Vardiyalar'

    def __str__(self):
        date = self.closed_at.strftime('%d.%m.%Y') if self.closed_at else 'Açık'
        return f'Vardiya {date} — {self.revenue / 100:.2f} TL ciro'


class Backup(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='Cihaz')
    filename = models.CharField(max_length=200, verbose_name='Dosya Adı')
    size_bytes = models.IntegerField(verbose_name='Boyut (bayt)')
    file = models.FileField(upload_to='backups/%Y/%m/', verbose_name='Dosya')
    stored_at = models.DateTimeField(auto_now_add=True, verbose_name='Depolama Tarihi')

    class Meta:
        unique_together = [('device', 'filename')]
        ordering = ['-stored_at']
        verbose_name = 'Yedek'
        verbose_name_plural = 'Yedekler'

    def __str__(self):
        return f'{self.filename} — {self.device}'
