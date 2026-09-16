from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

admin.site.site_header = 'Aksu Çınaraltı Yönetim Paneli'
admin.site.site_title = 'Aksu Yönetimi'
admin.site.index_title = 'İşletme Yönetimi'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('pos.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
