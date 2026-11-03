"""
Django settings for core project (Vercel deployment).

Secrets are read from environment variables. Set these in
Vercel -> Project -> Settings -> Environment Variables:

    SECRET_KEY
    DATABASE_URL
    CLOUDINARY_CLOUD_NAME
    CLOUDINARY_API_KEY
    CLOUDINARY_API_SECRET
    DEBUG                 (optional, "True" only for local development)
    CSRF_TRUSTED_ORIGINS  (optional, comma separated, e.g. https://mapsinfo1.vercel.app)
"""

from pathlib import Path
import os

import dj_database_url


BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Core / security
# ---------------------------------------------------------------------------

DEBUG = os.environ.get('DEBUG', 'False').strip().lower() in {'1', 'true', 'yes', 'on'}

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'dev-only-insecure-key-change-me'
    else:
        raise RuntimeError('SECRET_KEY environment variable is not set.')

ALLOWED_HOSTS = ['.vercel.app', 'localhost', '127.0.0.1']
# Add your custom domain here if you have one, e.g. 'www.example.com'

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'CSRF_TRUSTED_ORIGINS', 'https://mapsinfo1.vercel.app'
    ).split(',')
    if origin.strip()
]

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    # 'jazzmin' must come BEFORE django.contrib.admin
    'jazzmin',
    'cloudinary_storage',
    'store',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cloudinary',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

SITE_ID = 1

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # right after SecurityMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_processors.cart_item_count',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# ---------------------------------------------------------------------------
# Database (Neon Postgres via DATABASE_URL)
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=True,
        )
    }
elif DEBUG:
    # Local development: use the local SQLite file
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    raise RuntimeError('DATABASE_URL environment variable is not set.')


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'


# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files (served by WhiteNoise from inside the Django function)
# ---------------------------------------------------------------------------

STATIC_URL = '/static/'

# Your own static files (hero.png, logo.jpeg, ...). Make sure this folder
# exists and is committed to git.
STATICFILES_DIRS = [
    BASE_DIR / 'store' / 'static',
]

STATIC_ROOT = BASE_DIR / 'staticfiles'

# Lets WhiteNoise find admin/jazzmin/your static files at request time,
# so no collectstatic step is needed on Vercel.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True


# ---------------------------------------------------------------------------
# Media files (Cloudinary)
# ---------------------------------------------------------------------------

MEDIA_URL = '/media/'

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
    'API_KEY': os.environ.get('CLOUDINARY_API_KEY', ''),
    'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET', ''),
}

STORAGES = {
    'default': {
        'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage',
    },
    'staticfiles': {
        # Plain storage: manifest storage would break without collectstatic
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}


# ---------------------------------------------------------------------------
# Jazzmin admin theme
# ---------------------------------------------------------------------------

JAZZMIN_SETTINGS = {
    'site_title': 'Maps Info Admin',
    'site_header': 'Maps Info',
    'welcome_sign': 'Welcome to Maps Info admin',
    'copyright': 'Maps Info',
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'