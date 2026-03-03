#!/usr/bin/env bash
set -o errexit

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
if [ "${IMPORT_FIXTURE_ON_DEPLOY:-False}" = "True" ] && [ -f data/render_seed.json ]; then
  if python manage.py shell -c "from app.models import CustomUser, Station, Train, Booking; import sys; has_data = CustomUser.objects.exists() or Station.objects.exists() or Train.objects.exists() or Booking.objects.exists(); sys.exit(0 if has_data else 1)"; then
    echo "Seed data already present, skipping fixture import."
  else
    python manage.py loaddata data/render_seed.json
  fi
fi
python manage.py shell -c "
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.getenv('DJANGO_SUPERUSER_USERNAME')
email = os.getenv('DJANGO_SUPERUSER_EMAIL')
password = os.getenv('DJANGO_SUPERUSER_PASSWORD')

if username and email and password:
    user, created = User.objects.get_or_create(
        username=username,
        defaults={'email': email},
    )
    if created:
        user.set_password(password)
    if not getattr(user, 'email', ''):
        user.email = email
    if not user.is_staff:
        user.is_staff = True
    if not user.is_superuser:
        user.is_superuser = True
    user.save()
"
