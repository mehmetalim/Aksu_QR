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

## Ürün Görselleri

POS (`aksu-sistem`) ürün görsellerini `images/urun1.jpg` biçiminde göreli yolla gönderir.
Django bu dosyaları `static/images/` altından sunar — QR menü sayfası yolun başına
otomatik olarak `/static/` ekler.

`aksu-sistem/web/images/` içindeki görseller `aksu-django/static/images/` klasörüne
kopyalanmıştır. POS'a yeni bir görsel eklediğinizde buraya da kopyalayın:
```bash
cp ../aksu-sistem/web/images/*.jpg static/images/
docker compose up --build -d   # collectstatic yeniden çalışır
```
Ürün kaydındaki **Görsel yolu** alanına `images/urun1.jpg` formatında yazın
(başına `/static/` **yazmayın** — POS tarafı bu biçimi kabul etmez).

## POS ile Veri Sözleşmesi

| Alan | Davranış |
|------|----------|
| Kategori `icon` | POS'tan gelen simge saklanır ve katalog yayımında geri gönderilir |
| Kategori sırası | POS'un gönderdiği dizi sırası `Sıra` alanına yazılır |
| Katalog sürümü | Yalnızca gelen sürüm mevcuttan büyükse uygulanır; aynı sürüm yeniden gönderilirse üzerine yazılır |
| Yedekler | Cihaz ilk `POST /api/sync` öncesinde yedek gönderebilir; cihaz otomatik kaydedilir |

POS'un **Bulut & Yedek** paneli yalnızca `https://` adres kabul eder; yerel
`http://localhost:8000` ile denemek için POS'u kaynak koddan (`npm run dev`)
çalıştırın.
