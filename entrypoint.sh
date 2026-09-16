#!/bin/bash
set -e

echo "==> Veritabanı migrasyon uygulanıyor..."
python manage.py migrate --noinput

echo "==> Statik dosyalar derleniyor..."
python manage.py collectstatic --noinput --clear

echo "==> Gunicorn başlatılıyor..."
exec gunicorn aksu.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
