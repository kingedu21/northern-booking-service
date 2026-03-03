#!/usr/bin/env bash
set -o errexit

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
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
