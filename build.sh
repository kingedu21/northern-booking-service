#!/usr/bin/env bash
set -o errexit

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
python manage.py shell -c "import os; from django.contrib.auth import get_user_model; U=get_user_model(); u=os.getenv('DJANGO_SUPERUSER_USERNAME'); e=os.getenv('DJANGO_SUPERUSER_EMAIL'); p=os.getenv('DJANGO_SUPERUSER_PASSWORD'); (u and e and p) and (U.objects.filter(username=u).exists() or U.objects.create_superuser(u,e,p))"
