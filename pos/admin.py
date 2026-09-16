from django.contrib import admin
from django.utils.html import format_html

from .models import (Device, Category, Product, CatalogVersion, pos_slug,
                     SyncEvent, Order, Payment, CashMove, Shift, Backup)
from .signals import publish_catalog


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
    ordering = ['category__display_order', 'name']

    fieldsets = [
        (None, {'fields': ['product_id', 'name', 'category', 'active']}),
        ('Fiyat & İçerik', {'fields': ['price', 'description', 'image']}),
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
                ('Fiyat & İçerik', {'fields': ['price', 'description', 'image']}),
            ]
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'product_id' in form.base_fields:
            form.base_fields['product_id'].required = False
        return form

    def price_display(self, obj):
        return format_html('<strong>{} TL</strong>', f'{obj.price / 100:.2f}')
    price_display.short_description = 'Fiyat'
    price_display.admin_order_field = 'price'

    def save_model(self, request, obj, form, change):
        if not obj.product_id:
            obj.product_id = self._generate_product_id(obj.name)
        super().save_model(request, obj, form, change)
        publish_catalog()

    @staticmethod
    def _generate_product_id(name):
        """POS ile uyumlu (^[a-zA-Z0-9_-]{1,60}$) benzersiz bir ürün kodu üretir."""
        base = pos_slug(name)
        candidate = base
        suffix = 2
        while Product.objects.filter(product_id=candidate).exists():
            candidate = f'{base}-{suffix}'
            suffix += 1
        return candidate

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
    readonly_fields = ['event_id', 'device', 'seq', 'kind', 'occurred_at', 'received_at', 'payload']

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
