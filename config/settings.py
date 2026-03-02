import os
from pathlib import Path
import sys

import dj_database_url
import environ

# Load .env from config/ when running outside Docker (e.g. manage.py runserver, pytest)
BASE_DIR = Path(__file__).resolve().parent.parent
_env_file = Path(__file__).resolve().parent / ".env"
environ.Env.read_env(_env_file)

env = environ.Env(
    # set (casting, default value)
    DEBUG=(bool, False),
    SECRET_KEY=(str, "django-insecure"),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000", "http://localhost:8000"]),
    CSRF_TRUSTED_ORIGINS=(list, ["http://localhost:3000", "http://localhost:8000"]),
    SESSION_COOKIE_DOMAIN=(str, None),
    CSRF_COOKIE_DOMAIN=(str, None),
    DRF_THROTTLE_ANON_RATE=(str, "100/hour"),
    DRF_THROTTLE_USER_RATE=(str, "1000/hour"),
    SEARCH_AUTO_REINDEX=(bool, True),
    SEARCH_REINDEX_DEBOUNCE_SECONDS=(int, 30),
    # services
    IIIF_HOST=(str, "http://localhost:1024/"),
    MEILISEARCH_URL=(str, "http://localhost:7700"),
    MEILISEARCH_API_KEY=(str, ""),
    MEILISEARCH_INDEX_PREFIX=(str, ""),
    # App/project identity
    SITE_NAME=(str, "Archetype"),
    # Choices
    HISTORICAL_ITEM_TYPES=(list, ["Agreement", "Charter", "Letter"]),
    HISTORICAL_ITEM_HAIR_TYPES=(list, ["FHFH", "FHHF", "HFFH", "HFHF", "Mixed"]),
    REPOSITORY_TYPES=(list, ["Library", "Institution", "Person", "Online Resource"]),
    CHARACTER_ITEM_TYPES=(list, ["Majuscule Letter", "Minuscule Letter", "Numeral", "Punctuation", "Symbol", "Accent"]),
    # Celery
    CELERY_BROKER_URL=(str, "redis://redis:6379/0"),
    CELERY_RESULT_BACKEND=(str, "redis://redis:6379/0"),
)

SITE_NAME = env("SITE_NAME")

HISTORICAL_ITEM_TYPES = env("HISTORICAL_ITEM_TYPES")
HISTORICAL_ITEM_HAIR_TYPES = env("HISTORICAL_ITEM_HAIR_TYPES")
REPOSITORY_TYPES = env("REPOSITORY_TYPES")
CHARACTER_ITEM_TYPES = env("CHARACTER_ITEM_TYPES")
SEARCH_AUTO_REINDEX = env("SEARCH_AUTO_REINDEX")
SEARCH_REINDEX_DEBOUNCE_SECONDS = env("SEARCH_REINDEX_DEBOUNCE_SECONDS")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

SESSION_COOKIE_DOMAIN = env("SESSION_COOKIE_DOMAIN")
CSRF_COOKIE_DOMAIN = env("CSRF_COOKIE_DOMAIN")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    # 3rd-party apps
    "corsheaders",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "djoser",
    "django_extensions",
    "tinymce",
    "tagulous",
    "django_filters",
    # project apps
    "apps.common",
    "apps.users",
    "apps.scribes",
    "apps.symbols_structure",
    "apps.annotations",
    "apps.manuscripts",
    "apps.publications",
    "apps.search",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        conn_max_age=600,
        conn_health_checks=True,
        default=f"sqlite:///{BASE_DIR / 'local.db'}",
    ),
}

# Auto-switch to isolated sqlite database while running tests.
if "PYTEST_CURRENT_TEST" in os.environ or "test" in sys.argv:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "test.db",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Celery Configuration
CELERY_BROKER_URL = env("CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework.authentication.TokenAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticatedOrReadOnly",),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("DRF_THROTTLE_ANON_RATE"),
        "user": env("DRF_THROTTLE_USER_RATE"),
    },
    "DEFAULT_PAGINATION_CLASS": "config.pagination.BoundedLimitOffsetPagination",
    "PAGE_SIZE": 20,
}

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = "storage/media/"
STATIC_ROOT = BASE_DIR / "storage/staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
        }
    },
}

SERIALIZATION_MODULES = {
    "xml": "tagulous.serializers.xml_serializer",
    "json": "tagulous.serializers.json",
    "python": "tagulous.serializers.python",
    "yaml": "tagulous.serializers.pyyaml",
}

MEILISEARCH_URL = env("MEILISEARCH_URL")
MEILISEARCH_API_KEY = env("MEILISEARCH_API_KEY")
MEILISEARCH_INDEX_PREFIX = env("MEILISEARCH_INDEX_PREFIX")
IIIF_HOST = env("IIIF_HOST")

IIIF_PROFILES = {
    "thumbnail": {
        "host": IIIF_HOST,
        "region": "full",
        "size": "150,",
        "rotation": "0",
        "quality": "default",
        "format": "jpg",
    }
}
