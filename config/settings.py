"""
Django settings for archetype project.

Generated by 'django-admin startproject' using Django 5.0.7.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""

from pathlib import Path

import environ

env = environ.Env(
    # set (casting, default value)
    DEBUG=(bool, False),
    SECRET_KEY=(str, "django-insecure"),
    ALLOWED_HOSTS=(list, ["localhost"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000", "http://localhost:8000"]),
    CSRF_TRUSTED_ORIGINS=(list, ["http://localhost:3000", "http://localhost:8000"]),
    IIIF_HOST=(str, "http://localhost:1024/"),
    SITE_NAME=(str, "Site Name"),
)

SITE_NAME = env("SITE_NAME")

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    # "admin_interface",
    # "colorfield",
    "config.apps.ArcheTypeAdminConfig",
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
    "haystack",
    "haystack_rest",
    "admin_ordering",
    "nested_admin",
    # project apps
    "apps.common",
    "apps.users",
    "apps.publications",
    "apps.scribes",
    "apps.symbols_structure",
    "apps.annotations",
    "apps.manuscripts",
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

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        conn_max_age=600,
        conn_health_checks=True,
    ),
}

# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    # {
    #     "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    # },
    # {
    #     "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    # },
    # {
    #     "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    # },
    # {
    #     "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    # },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework.authentication.TokenAuthentication",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 20,
}

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/
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
            "level": "INFO",  # Adjust if you want more or fewer Django logs
        }
    },
}

SERIALIZATION_MODULES = {
    "xml": "tagulous.serializers.xml_serializer",
    "json": "tagulous.serializers.json",
    "python": "tagulous.serializers.python",
    "yaml": "tagulous.serializers.pyyaml",
}

# -------------- Haystack settings --------------
HAYSTACK_CONNECTIONS = {
    "default": {
        "ENGINE": "haystack.backends.elasticsearch7_backend.Elasticsearch7SearchEngine",
        "URL": "http://elasticsearch:9200/",
        "INDEX_NAME": "haystack",
    },
}
# HAYSTACK_CONNECTIONS = {
#     "default": {
#         "ENGINE": "haystack.backends.simple_backend.SimpleEngine",
#     },
# }

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
