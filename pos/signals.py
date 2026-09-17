from django.db import transaction
from django.utils import timezone


def publish_catalog(source='admin'):
    """
    Tüm kategori ve ürünleri okuyup yeni bir CatalogVersion oluşturur.
    Django admin'de herhangi bir ürün/kategori kaydedildiğinde çağrılır.
    POS bu sürümü bir sonraki sync'te otomatik olarak alır.
    """
    from .models import Category, Product, CatalogVersion

    with transaction.atomic():
        latest = CatalogVersion.objects.select_for_update().order_by('-version').first()
        new_version = (latest.version if latest else 0) + 1

        categories = [
            {'id': c.category_id, 'name': c.name, 'icon': c.icon}
            for c in Category.objects.order_by('display_order', 'name')
        ]
        products = [
            {
                'id': p.product_id,
                'name': p.name,
                'category': p.category.category_id,
                'price': p.price,
                'active': p.active,
                'description': p.description,
                'image': p.image,
            }
            # POS'un gönderdiği sırayı koru — QR menü ile POS aynı sırayı gösterir.
            for p in Product.objects.select_related('category').order_by('sort_order', 'name')
        ]

        snapshot = {
            'version': new_version,
            'categories': categories,
            'products': products,
            'publishedAt': timezone.now().isoformat(),
        }

        CatalogVersion.objects.create(version=new_version, source=source, snapshot=snapshot)
        return new_version
