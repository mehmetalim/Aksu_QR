from decimal import Decimal

from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import (Device, Category, Product, CatalogVersion, next_product_id,
                     SyncEvent, Order, Payment, CashMove, Shift, Backup)
from .signals import publish_catalog


def _store_product_image(upload):
    """
    Yüklenen görseli static/images/ altına yazar ve dosya adını döner.
    POS ile aynı yol biçimi (images/dosya.jpg) korunur; QR menü bunu
    /static/images/... olarak sunar.
    """
    from django.conf import settings
    from django.utils.text import get_valid_filename
    from .models import pos_slug

    folder = settings.BASE_DIR / 'static' / 'images'
    folder.mkdir(parents=True, exist_ok=True)

    stem, dot, ext = get_valid_filename(upload.name).rpartition('.')
    name = f'{pos_slug(stem or upload.name, "urun")}.{(ext or "jpg").lower()}'
    target = folder / name
    counter = 2
    while target.exists():
        name = f'{pos_slug(stem or upload.name, "urun")}-{counter}.{(ext or "jpg").lower()}'
        target = folder / name
        counter += 1

    with open(target, 'wb') as out:
        for chunk in upload.chunks():
            out.write(chunk)
    return name


class ProductForm(forms.ModelForm):
    """Fiyat alanını TL olarak gösterir; veritabanına kuruş olarak yazar."""

    price_tl = forms.DecimalField(
        label='Fiyat (TL)', max_digits=10, decimal_places=2, min_value=Decimal('0'), localize=True,
        help_text='Örnek: 180,50 — kuruş değil TL girin.',
    )
    image_upload = forms.ImageField(
        label='Görsel yükle', required=False,
        help_text='Bilgisayarınızdan seçin. Dosya static/images/ altına kaydedilir '
                  've "Görsel yolu" otomatik doldurulur.',
    )

    class Meta:
        model = Product
        fields = ['product_id', 'name', 'category', 'active',
                  'price_tl', 'description', 'image', 'sort_order']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['price_tl'].initial = Decimal(self.instance.price) / 100
        if 'product_id' in self.fields:
            self.fields['product_id'].required = False
        self.fields['image'].required = False
        self.fields['image'].help_text = (
            'POS ile ortak biçim: images/dosya.jpg. Yukarıdan dosya yüklerseniz '
            'bu alan kendiliğinden dolar.'
        )

    def clean(self):
        data = super().clean()
        upload = data.get('image_upload')
        if upload:
            data['image'] = 'images/' + _store_product_image(upload)
        return data

    def save(self, commit=True):
        product = super().save(commit=False)
        product.price = int((self.cleaned_data['price_tl'] * 100).to_integral_value())
        if self.cleaned_data.get('image'):
            product.image = self.cleaned_data['image']
        if commit:
            product.save()
        return product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'category_id', 'icon', 'display_order']
    list_editable = ['display_order']
    ordering = ['display_order', 'name']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        publish_catalog()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        publish_catalog()


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price_display', 'active', 'updated_at']
    list_filter = ['category', 'active']
    list_editable = ['active']
    search_fields = ['name', 'product_id', 'description']
    ordering = ['sort_order', 'name']

    form = ProductForm

    fieldsets = [
        (None, {'fields': ['product_id', 'name', 'category', 'active']}),
        ('Fiyat & İçerik', {'fields': ['price_tl', 'description', 'image_upload', 'image', 'sort_order']}),
        ('Meta', {'fields': ['updated_at']}),
    ]

    def get_readonly_fields(self, request, obj=None):
        # Ürün kodu POS tarafında kalıcı anahtardır; bir kez yazıldıktan sonra
        # değiştirilmemeli. Ama ekleme formunda (ve kodu boş kalmış bozuk
        # kayıtlarda) girilebilir olmalı — aksi halde boş kaydedilir ve POS
        # "Ürün kimliği geçersiz." hatası verir.
        if obj and obj.product_id:
            return ['product_id', 'updated_at']
        return ['updated_at']

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return [
                (None, {'fields': ['product_id', 'name', 'category', 'active']}),
                ('Fiyat & İçerik', {'fields': ['price_tl', 'description', 'image_upload', 'image', 'sort_order']}),
            ]
        return super().get_fieldsets(request, obj)

    def price_display(self, obj):
        return format_html('<strong>{} TL</strong>', f'{obj.price / 100:.2f}')
    price_display.short_description = 'Fiyat'
    price_display.admin_order_field = 'price'

    def save_model(self, request, obj, form, change):
        # Kod girilmediyse kategorinin kısa kod düzenini sürdür: k1, k2, e22…
        if not obj.product_id:
            obj.product_id = next_product_id(obj.category)
        if not change and not obj.sort_order:
            # Yeni ürün listenin sonuna eklenir (sıra POS ile ortak).
            last = Product.objects.order_by('-sort_order').first()
            obj.sort_order = (last.sort_order + 1) if last else 0
        super().save_model(request, obj, form, change)
        publish_catalog()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        publish_catalog()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        publish_catalog()


@admin.register(CatalogVersion)
class CatalogVersionAdmin(admin.ModelAdmin):
    list_display = ['version', 'source', 'product_count', 'published_at']
    readonly_fields = ['version', 'source', 'published_at', 'snapshot']
    ordering = ['-version']

    def product_count(self, obj):
        return len(obj.snapshot.get('products', []))
    product_count.short_description = 'Ürün Sayısı'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_device_id', 'is_active', 'last_sync_at', 'registered_at']
    list_filter = ['is_active']
    list_editable = ['is_active']

    def short_device_id(self, obj):
        return obj.device_id[:16] + '…'
    short_device_id.short_description = 'Cihaz Kimliği'


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ['date_display', 'device', 'revenue_display', 'opened_at', 'closed_at']
    list_filter = ['device', 'closed_at']
    ordering = ['-closed_at']
    readonly_fields = ['shift_id', 'device', 'opened_at', 'closed_at',
                       'opening_cash', 'revenue', 'totals', 'body']

    def date_display(self, obj):
        return obj.closed_at.strftime('%d.%m.%Y') if obj.closed_at else 'Açık'
    date_display.short_description = 'Tarih'

    def revenue_display(self, obj):
        return format_html('<strong>{} TL</strong>', f'{obj.revenue / 100:.2f}')
    revenue_display.short_description = 'Ciro'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_id_short', 'device', 'method', 'total_display', 'occurred_at']
    list_filter = ['method', 'device']
    ordering = ['-occurred_at']
    readonly_fields = ['payment_id', 'device', 'order', 'shift_id',
                       'method', 'total', 'gift', 'occurred_at', 'body']

    def payment_id_short(self, obj):
        return obj.payment_id[:16] + '…'
    payment_id_short.short_description = 'Ödeme Kimliği'

    def total_display(self, obj):
        return f'{obj.total / 100:.2f} TL'
    total_display.short_description = 'Tutar'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SyncEvent)
class SyncEventAdmin(admin.ModelAdmin):
    list_display = ['event_id_short', 'device', 'kind', 'seq', 'occurred_at', 'received_at']
    list_filter = ['kind', 'device']
    readonly_fields = ['event_id', 'device', 'seq', 'kind', 'occurred_at', 'received_at']

    def event_id_short(self, obj):
        return obj.event_id[:16] + '…'
    event_id_short.short_description = 'Olay Kimliği'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Backup)
class BackupAdmin(admin.ModelAdmin):
    list_display = ['filename', 'device', 'size_display', 'stored_at']
    readonly_fields = ['device', 'filename', 'size_bytes', 'stored_at', 'file']

    def size_display(self, obj):
        kb = obj.size_bytes / 1024
        if kb > 1024:
            return f'{kb / 1024:.1f} MB'
        return f'{kb:.1f} KB'
    size_display.short_description = 'Boyut'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_id_short', 'device', 'table_id', 'status', 'opened_at', 'closed_at']
    list_filter = ['status', 'device']
    readonly_fields = ['order_id', 'device', 'table_id', 'status',
                       'opened_at', 'closed_at', 'body', 'synced_at']

    def order_id_short(self, obj):
        return obj.order_id[:16] + '…'
    order_id_short.short_description = 'Sipariş Kimliği'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CashMove)
class CashMoveAdmin(admin.ModelAdmin):
    list_display = ['occurred_at', 'device', 'amount_display', 'reason']
    list_filter = ['device']
    readonly_fields = ['move_id', 'device', 'shift_id', 'amount', 'reason', 'occurred_at']

    def amount_display(self, obj):
        sign = '+' if obj.amount > 0 else ''
        return f'{sign}{obj.amount / 100:.2f} TL'
    amount_display.short_description = 'Tutar'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
