from django.urls import path, re_path
from . import views

urlpatterns = [
    # POS sync API
    path('api/sync', views.sync_events, name='sync_events'),
    path('api/catalog', views.get_catalog, name='get_catalog'),
    path('api/reports', views.get_reports, name='get_reports'),

    # Backup API
    re_path(
        r'^api/backups/(?P<device_id>[\w\-]+)/(?P<filename>[\w.\-]+\.aksu-backup)$',
        views.handle_backup,
        name='handle_backup',
    ),

    # Public menu API (QR menü JS bu endpoint'i kullanır)
    path('api/menu', views.get_menu, name='get_menu'),

    # QR menü sayfası
    path('menu/', views.qr_menu_page, name='qr_menu'),
    path('', views.qr_menu_page, name='home'),
]
