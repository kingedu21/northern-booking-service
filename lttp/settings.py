
import os
import socket
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


BASE_DIR = Path(__file__).resolve().parent.parent


load_dotenv(BASE_DIR / ".env")


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", "False") == "True"

_allowed_hosts_raw = os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts_raw.split(",") if host.strip()]
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
ALLOWED_HOSTS = list(dict.fromkeys(ALLOWED_HOSTS))
if DEBUG:
    for tunnel_host in [".ngrok-free.app", ".ngrok-free.dev", ".ngrok.io", ".loca.lt", ".trycloudflare.com"]:
        if tunnel_host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(tunnel_host)

# Respect proxy/tunnel HTTPS header when present (ngrok/cloudflare/localtunnel).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = ["https://*.onrender.com"]
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    "django.middleware.csrf.CsrfViewMiddleware",
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'lttp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'lttp.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }


DATABASES = {
    "default": dj_database_url.config(
        conn_max_age=600,
        ssl_require=os.getenv("DB_SSL_REQUIRE", "True") == "True"
    )
}

# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Africa/Nairobi'

USE_I18N = True

USE_TZ = True

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@yourdomain.com")


# AUTH_USER_MODEL = 'app.CustomUser'

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")


# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "app.CustomUser"

LOGOUT_REDIRECT_URL = "/"

# Redis cache/locking config.
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
USE_REDIS_CACHE = env_bool("USE_REDIS_CACHE", True)

def _locmem_cache_config():
    return {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "railway-ticketing-local-cache",
            "TIMEOUT": 300,
        }
    }


def _redis_available(redis_url):
    try:
        import redis

        client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        client.ping()
        return True
    except (ImportError, OSError, socket.error, Exception):
        return False


if USE_REDIS_CACHE and _redis_available(REDIS_URL):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": 300,
        }
    }
else:
    CACHES = _locmem_cache_config()

SEAT_LOCK_TTL_SECONDS = int(os.getenv("SEAT_LOCK_TTL_SECONDS", "30"))
SEAT_AVAILABILITY_CACHE_TTL_SECONDS = int(os.getenv("SEAT_AVAILABILITY_CACHE_TTL_SECONDS", "30"))
SCHEDULE_CACHE_TTL_SECONDS = int(os.getenv("SCHEDULE_CACHE_TTL_SECONDS", "300"))
UNPAID_BOOKING_HOLD_SECONDS = int(os.getenv("UNPAID_BOOKING_HOLD_SECONDS", "60"))

# settings.py

MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE", "174379")  # Sandbox PayBill
MPESA_PASSKEY = os.getenv(
    "MPESA_PASSKEY",
    "",
)
MPESA_CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY", "")
MPESA_CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET", "")
MPESA_CALLBACK_URL = os.getenv("MPESA_CALLBACK_URL", "https://your-public-domain/mpesa_callback/")
MPESA_CALLBACK_TIMEOUT_SECONDS = int(os.getenv("MPESA_CALLBACK_TIMEOUT_SECONDS", "180"))
MPESA_STK_QUERY_MIN_INTERVAL_SECONDS = int(os.getenv("MPESA_STK_QUERY_MIN_INTERVAL_SECONDS", "15"))
MPESA_STK_QUERY_RATE_LIMIT_BACKOFF_SECONDS = int(os.getenv("MPESA_STK_QUERY_RATE_LIMIT_BACKOFF_SECONDS", "30"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

