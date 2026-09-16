from django.db import migrations
from django.utils.text import slugify

TR_MAP = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosucgiosu')


def backfill(apps, schema_editor):
    """
    Admin ekleme formu ürün kodunu salt-okunur gösterdiği için boş kaydedilmiş
    ürünler olabilir. POS bu kayıtlar yüzünden "Ürün kimliği geçersiz." hatası
    verir; onlara POS ile uyumlu bir kod üretiyoruz.
    """
    Product = apps.get_model('pos', 'Product')
    for product in Product.objects.filter(product_id=''):
        base = slugify(product.name.translate(TR_MAP))[:50].strip('-') or 'urun'
        candidate = base
        suffix = 2
        while Product.objects.filter(product_id=candidate).exclude(pk=product.pk).exists():
            candidate = f'{base}-{suffix}'
            suffix += 1
        product.product_id = candidate
        product.save(update_fields=['product_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0003_alter_category_category_id_alter_product_product_id'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
