# Aksu Django Backend — Kurulum Kılavuzu

## Yerel Geliştirme

```bash
cd aksu-django
cp .env.example .env
# .env dosyasını düzenleyin

docker compose up --build
# http://localhost:8000 → QR Menü
# http://localhost:8000/admin → Yönetim paneli
```

İlk admin kullanıcısı oluşturmak için:
```bash
docker compose exec web python manage.py createsuperuser
```

Migration dosyaları repoya dahildir; `entrypoint.sh` her açılışta `migrate` çalıştırır.
Yalnızca **model değiştirdiyseniz** yeni migration üretin ve repoya ekleyin:
```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

## Coolify Üzerinden Deploy

1. Coolify'da **New Resource → Docker Compose** seçin
2. Bu klasörü Git reposuna push edin, repoyu bağlayın
3. **Environment Variables** bölümüne `.env.example`'daki değişkenleri girin:
   - `SECRET_KEY` — en az 50 karakterlik rastgele değer
   - `DEBUG=False`
   - `ALLOWED_HOSTS=aksu.conaco.dev`
   - `DB_NAME=aksu`, `DB_USER=aksu`, `DB_PASSWORD=<güçlü parola>`
   - `DB_HOST=db` (docker-compose servis adı)
   - `SYNC_TOKEN=<en az 32 karakterlik gizli anahtar>`
4. Domain: `aksu.conaco.dev` → Coolify otomatik SSL ayarlar
5. Deploy edin

## Windows POS Bağlantısı

POS uygulamasında **Yönetici → Bulut & Yedek** paneline gidin:
- **Cloudflare uygulama adresi**: `https://aksu.conaco.dev`
- **Cihaz bağlantı anahtarı**: Django'daki `SYNC_TOKEN` değeri

Kaydet → Şimdi Eşitle.

## Senkronizasyon Akışı

```
POS (offline çalışır)
  ↓ İnternet geldiğinde (her 30 sn)
POST /api/sync
  Body: { deviceId, catalogVersion, events: [...] }
  Response: { accepted: [...], catalog: null | {...} }

Eğer Django admin fiyat güncelledi ise:
  Response'da catalog: { version: N+1, products: [...] }
  POS bunu otomatik uygular, QR menü de güncellenir.
```

## API Endpoint'leri

| Yöntem | Yol | Açıklama |
|--------|-----|----------|
| POST | `/api/sync` | POS → Django event sync (Bearer auth) |
| GET | `/api/catalog?version=N` | POS katalog poll (Bearer auth) |
| GET | `/api/menu` | Public QR menü verisi (auth yok) |
| GET | `/api/reports` | Gün sonu raporları (Bearer auth) |
| PUT | `/api/backups/{id}/{file}` | Şifreli yedek yükle (Bearer auth) |
| GET | `/api/backups/{id}/{file}` | Yedek indir (Bearer auth) |
| GET | `/` veya `/menu/` | QR menü sayfası |
| GET | `/admin/` | Django yönetim paneli |

## Ürün Ekleme

Admin → **Ürünler → Ürün Ekle**:

- **Ürün kodu**: boş bırakın; kategorinin kısa kod düzeni sürdürülerek otomatik atanır
  (kahvaltı → `k9`, kebap → `e31`, içecekler → `ic13`). Kaydedildikten sonra değişmez —
  POS tarafında kalıcı anahtardır.
- **Fiyat**: **TL** olarak girilir (`180,50`). Veritabanında kuruş tutulur, dönüşüm otomatiktir.
- **Sıra**: POS ve QR menüde görünme sırası. Yeni ürün listenin sonuna eklenir.

## Ürün Görselleri

Ürün formundaki **Görsel yükle** alanından bilgisayarınızdan dosya seçin. Dosya
`static/images/` altına kaydedilir ve **Görsel yolu** alanı `images/dosya.jpg`
biçiminde otomatik dolar. QR menü sayfası yolun başına `/static/` ekleyerek sunar.

Yüklemeden sonra statik dosyaların yeniden derlenmesi gerekir:
```bash
docker compose restart web     # entrypoint collectstatic çalıştırır
```

**POS ekranında da görünmesi için**: Windows POS ürün görsellerini kendi klasöründen
(`aksu-sistem/web/images/`) okur. Django'ya yüklediğiniz dosyanın aynısını oraya da
kopyalayın; aksi halde görsel yalnızca QR menüde görünür, POS'ta boş kalır.
```bash
cp static/images/yeni-urun.jpg ../aksu-sistem/web/images/
```

**Görsel yolu** alanını elle yazacaksanız `images/urun1.jpg` biçimini kullanın —
başına `/static/` **yazmayın**, POS tarafı bu biçimi kabul etmez.

## POS ile Veri Sözleşmesi

| Alan | Davranış |
|------|----------|
| Kategori `icon` | POS'tan gelen simge saklanır ve katalog yayımında geri gönderilir |
| Ürün sırası | POS'un dizi sırası `Sıra` alanına yazılır; QR menü ve POS **aynı sırayı** gösterir |
| Ürün silme | Katalog tam anlık görüntüdür: bir tarafta silinen ürün diğerinden de kalkar |
| Fiyat | Admin'de **TL**, veritabanı ve API'de kuruş |
| Katalog sürümü | Yalnızca gelen sürüm mevcuttan büyükse uygulanır; aynı sürüm yeniden gönderilirse üzerine yazılır |
| Senkronizasyon olayları | Yalnızca kimlik/sıra saklanır (tekrar gönderimleri elemek için), içerik saklanmaz ve 30 günden eski kayıtlar silinir |
| Yedekler | Cihaz ilk `POST /api/sync` öncesinde yedek gönderebilir; cihaz otomatik kaydedilir |

POS'un **Bulut & Yedek** paneli yalnızca `https://` adres kabul eder; yerel
`http://localhost:8000` ile denemek için POS'u kaynak koddan (`npm run dev`)
çalıştırın.
