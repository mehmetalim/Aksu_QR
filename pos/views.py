import json
import re
import hashlib
import hmac
from datetime import datetime

from django.conf import settings
from django.http import JsonResponse, FileResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.files.base import ContentFile

from .models import (Device, Category, Product, CatalogVersion, pos_slug,
                     SyncEvent, Order, Payment, CashMove, Shift, Backup)
from .signals import publish_catalog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


def _fail(msg, status=400):
    return _json({'error': msg}, status=status)


def _auth(request):
    """Constant-time Bearer token check."""
    token = getattr(settings, 'SYNC_TOKEN', '')
    if not token or len(token) < 32:
        return False
    supplied = request.headers.get('Authorization', '')
    expected = f'Bearer {token}'
    return hmac.compare_digest(
        hashlib.sha256(supplied.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


def _parse_dt(value):
    """Parse ISO datetime string; returns timezone-aware datetime or None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            from django.utils.timezone import make_aware
            dt = make_aware(dt)
        return dt
    except (ValueError, TypeError):
        return None


def _safe_int(value, default=0):
    """Tolerate null / non-numeric values coming from the POS client."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


POS_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,60}$')


def _unique_product_id(base):
    candidate = base
    suffix = 2
    while Product.objects.filter(product_id=candidate).exists():
        candidate = f'{base}-{suffix}'
        suffix += 1
    return candidate


def _apply_catalog_payload(payload, source='pos'):
    """
    Sync incoming catalog payload into Category + Product tables
    and create a new CatalogVersion entry.
    """
    categories = payload.get('categories', [])
    products = payload.get('products', [])

    for order, cat in enumerate(categories):
        # POS kategori sırasını dizi sırasından korur; simge de round-trip'te kaybolmaz.
        Category.objects.update_or_create(
            category_id=str(cat['id']),
            defaults={
                'name': str(cat.get('name', ''))[:160],
                'icon': str(cat.get('icon', ''))[:8],
                'display_order': order,
            },
        )

    for p in products:
        cat_obj = Category.objects.filter(category_id=str(p.get('category', ''))).first()
        if not cat_obj:
            continue
        # Eski sürümlerin ürettiği boş/geçersiz kodlar POS'ta "Ürün kimliği
        # geçersiz." hatasına yol açıyor; kaydı düşürmek yerine kodu onarıyoruz.
        product_id = str(p.get('id', ''))
        if not POS_ID_RE.match(product_id):
            product_id = _unique_product_id(pos_slug(p.get('name', '')))
        Product.objects.update_or_create(
            product_id=product_id,
            defaults={
                'name': str(p.get('name', ''))[:160],
                'category': cat_obj,
                'price': int(p.get('price', 0)),
                'active': bool(p.get('active', True)),
                'description': str(p.get('description', ''))[:1000],
                'image': str(p.get('image', ''))[:200],
            },
        )

    version = _safe_int(payload.get('version'))
    CatalogVersion.objects.update_or_create(
        version=version,
        defaults={'source': source, 'snapshot': payload},
    )


def _process_event(device, event):
    """Update structured DB tables from a single sync event."""
    kind = event.get('kind', '')
    payload = event.get('payload', {})

    # ---- catalog ----
    if kind == 'catalog':
        latest = CatalogVersion.objects.order_by('-version').first()
        current = latest.version if latest else 0
        incoming = _safe_int(payload.get('version'))
        if incoming > current or not latest:
            _apply_catalog_payload(payload, source='pos')

    # ---- order ----
    elif kind == 'order':
        opened = _parse_dt(payload.get('openedAt')) or timezone.now()
        closed = _parse_dt(payload.get('closedAt'))
        Order.objects.update_or_create(
            order_id=str(payload.get('id', '')),
            defaults={
                'device': device,
                'table_id': str(payload.get('tableId', '')),
                'status': str(payload.get('status', 'open')),
                'opened_at': opened,
                'closed_at': closed,
                'body': payload,
            },
        )

    # ---- payment / void ----
    elif kind in ('payment', 'void'):
        payment_data = payload.get('payment') if kind == 'payment' else None
        order_data = payload.get('order', {}) if kind in ('payment', 'void') else payload

        if order_data.get('id'):
            order_obj = Order.objects.filter(order_id=order_data['id']).first()
            if order_obj:
                order_obj.status = order_data.get('status', order_obj.status)
                order_obj.body = order_data
                closed = _parse_dt(order_data.get('closedAt'))
                if closed and not order_obj.closed_at:
                    order_obj.closed_at = closed
                order_obj.save()

        if payment_data and payment_data.get('id'):
            occurred = _parse_dt(payment_data.get('at')) or timezone.now()
            order_obj = Order.objects.filter(order_id=payment_data.get('orderId', '')).first()
            Payment.objects.update_or_create(
                payment_id=str(payment_data['id']),
                defaults={
                    'device': device,
                    'order': order_obj,
                    'shift_id': str(payment_data.get('shiftId', '')),
                    'method': str(payment_data.get('method', 'cash')),
                    'total': int(payment_data.get('total', 0)),
                    'gift': int(payment_data.get('gift', 0)),
                    'occurred_at': occurred,
                    'body': payment_data,
                },
            )

    # ---- cash ----
    elif kind == 'cash':
        occurred = _parse_dt(payload.get('at')) or timezone.now()
        CashMove.objects.update_or_create(
            move_id=str(payload.get('id', '')),
            defaults={
                'device': device,
                'shift_id': str(payload.get('shiftId', '')),
                'amount': int(payload.get('amount', 0)),
                'reason': str(payload.get('reason', ''))[:300],
                'occurred_at': occurred,
            },
        )

    # ---- day-close ----
    elif kind == 'day-close':
        shift_data = payload.get('shift', {})
        opened = _parse_dt(shift_data.get('openedAt')) or timezone.now()
        closed = _parse_dt(payload.get('closedAt')) or timezone.now()
        Shift.objects.update_or_create(
            shift_id=str(shift_data.get('id', '')),
            defaults={
                'device': device,
                'opened_at': opened,
                'closed_at': closed,
                'opening_cash': int(shift_data.get('opening', 0)),
                'revenue': int(payload.get('totals', {}).get('revenue', 0)),
                'totals': payload.get('totals', {}),
                'body': payload,
            },
        )


# ---------------------------------------------------------------------------
# API Views
# ---------------------------------------------------------------------------

VALID_EVENT_KINDS = frozenset(
    ['catalog', 'order', 'payment', 'void', 'cash', 'day-close', 'security']
)


@csrf_exempt
@require_http_methods(['POST'])
def sync_events(request):
    """
    POST /api/sync
    POS → Django: olay paketi gönderir.
    Django → POS: onaylanan ID'ler + (varsa) güncel katalog döner.
    """
    if not _auth(request):
        return _fail('Yetkisiz istek.', 401)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _fail('Geçersiz JSON.')

    device_id = str(data.get('deviceId', '')).strip()
    if not device_id:
        return _fail('Cihaz kimliği gerekli.')

    device, _ = Device.objects.get_or_create(
        device_id=device_id,
        defaults={'name': f'POS {device_id[:8]}'},
    )

    events = data.get('events', [])
    if not isinstance(events, list) or not events or len(events) > 10:
        return _fail('Geçersiz olay listesi (1-10 olay bekleniyor).')

    accepted = []
    for ev in events:
        event_id = str(ev.get('id', '')).strip()
        kind = str(ev.get('kind', '')).strip()
        seq = ev.get('seq')

        if (not event_id or kind not in VALID_EVENT_KINDS
                or not isinstance(seq, int) or seq < 1):
            return _fail(f'Geçersiz olay formatı: {event_id}')

        occurred = _parse_dt(ev.get('at')) or timezone.now()
        _, created = SyncEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                'device': device,
                'seq': seq,
                'kind': kind,
                'occurred_at': occurred,
                'payload': ev.get('payload', {}),
            },
        )
        if created:
            try:
                _process_event(device, ev)
            except Exception:
                pass  # tek hatalı olay, sync'in tamamını engellemez

        accepted.append(event_id)

    device.last_sync_at = timezone.now()
    device.save(update_fields=['last_sync_at'])

    # Katalog güncelleme gerekiyor mu?
    client_version = _safe_int(data.get('catalogVersion'))
    latest = CatalogVersion.objects.order_by('-version').first()
    catalog = None
    if latest and latest.version > client_version:
        catalog = latest.snapshot

    return _json({'accepted': accepted, 'catalog': catalog})


@require_http_methods(['GET'])
def get_catalog(request):
    """
    GET /api/catalog?version=N
    POS, bekleyen olayı olmadığında bu endpoint'i poll eder.
    Django versiyonu daha yüksekse katalog döner, yoksa null.
    """
    if not _auth(request):
        return _fail('Yetkisiz istek.', 401)
    client_version = _safe_int(request.GET.get('version'))
    latest = CatalogVersion.objects.order_by('-version').first()
    if not latest or latest.version <= client_version:
        return _json({'catalog': None})
    return _json({'catalog': latest.snapshot})


@require_http_methods(['GET'])
def get_menu(request):
    """
    GET /api/menu
    Public endpoint — QR menü JS bu endpoint'i kullanır.
    """
    latest = CatalogVersion.objects.order_by('-version').first()
    if not latest:
        return _fail('Menü henüz yayımlanmadı.', 503)
    return _json(latest.snapshot)


@require_http_methods(['GET'])
def get_reports(request):
    """
    GET /api/reports
    Admin: gün sonu raporları (en yeni 100 vardiya).
    """
    if not _auth(request):
        return _fail('Yetkisiz istek.', 401)
    shifts = Shift.objects.filter(closed_at__isnull=False).order_by('-closed_at')[:100]
    return _json({'reports': [s.body for s in shifts]})


@csrf_exempt
def handle_backup(request, device_id, filename):
    """
    PUT /api/backups/{device_id}/{filename}  — şifreli yedek yükle
    GET /api/backups/{device_id}/{filename}  — yedek indir
    """
    if not _auth(request):
        return _fail('Yetkisiz istek.', 401)

    if not re.match(r'^[\w.\-]+\.aksu-backup$', filename):
        return _fail('Dosya adı geçersiz.')

    if request.method == 'PUT':
        # POS ilk yedeğini ilk sync'ten önce gönderebilir; cihazı burada da kaydet.
        device, _ = Device.objects.get_or_create(
            device_id=device_id,
            defaults={'name': f'POS {device_id[:8]}'},
        )
    else:
        device = Device.objects.filter(device_id=device_id).first()
        if not device:
            return _fail('Cihaz bulunamadı.', 404)

    if request.method == 'PUT':
        body = request.read()
        if len(body) < 5 or body[:5] != b'AKSU2':
            return _fail('Yedek biçimi geçersiz.')
        if len(body) > 64 * 1024 * 1024:
            return _fail('Yedek dosyası çok büyük (max 64 MB).', 413)

        content = ContentFile(body, name=filename)
        backup_obj, _ = Backup.objects.get_or_create(
            device=device, filename=filename,
            defaults={'size_bytes': len(body)},
        )
        if backup_obj.file:
            backup_obj.file.delete(save=False)
        backup_obj.file.save(filename, content, save=True)
        backup_obj.size_bytes = len(body)
        backup_obj.save(update_fields=['size_bytes'])
        return _json({'ok': True})

    if request.method == 'GET':
        backup_obj = Backup.objects.filter(device=device, filename=filename).first()
        if not backup_obj or not backup_obj.file:
            return _fail('Yedek bulunamadı.', 404)
        return FileResponse(
            backup_obj.file.open('rb'),
            content_type='application/octet-stream',
            as_attachment=True,
            filename=filename,
        )

    return _fail('Yöntem desteklenmiyor.', 405)


# ---------------------------------------------------------------------------
# QR Menü Sayfası
# ---------------------------------------------------------------------------

def qr_menu_page(request):
    """Müşterilere QR kod ile gösterilen menü sayfası."""
    # Ürün görselleri JS tarafında kuruluyor ({% static %} çalışma anında kullanılamaz),
    # bu yüzden STATIC_URL'i şablona veriyoruz.
    return render(request, 'pos/menu.html', {'static_url': settings.STATIC_URL})
