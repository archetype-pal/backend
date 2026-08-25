import os
from pathlib import Path
import sys

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
import environ

# Read in both contexts — host-native (manage.py, pytest) and in-container via
# the compose bind mount. Explicit container env wins: read_env uses setdefault.
BASE_DIR = Path(__file__).resolve().parent.parent
_env_file = BASE_DIR / "config" / ".env"
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
    # Blanket buckets; the 10:1 anon:user ratio is deliberate. History: archetype-pal/backend#168.
    DRF_THROTTLE_ANON_RATE=(str, "3000/hour"),
    DRF_THROTTLE_USER_RATE=(str, "30000/hour"),
    DRF_NUM_PROXIES=(int, None),
    SEARCH_AUTO_REINDEX=(bool, True),
    SEARCH_REINDEX_DEBOUNCE_SECONDS=(int, 30),
    # services
    IIIF_HOST=(str, "http://localhost:8182/"),
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
    # Cache used for cross-process locks (e.g. the search reindex single-flight).
    CACHE_URL=(str, "redis://redis:6379/1"),
    # Production HTTPS hardening (only applied when DEBUG is off).
    SECURE_SSL_REDIRECT=(bool, True),
    SECURE_HSTS_SECONDS=(int, 60 * 60 * 24 * 365),
    # Logging
    APP_LOG_LEVEL=(str, "INFO"),
    LOG_IN_FILE=(bool, False),
    # Chunked image uploads (apps.uploads)
    UPLOADS_MAX_BYTES=(int, 6 * 1024**3),
    UPLOADS_CHUNK_SIZE=(int, 100 * 1024**2),
    UPLOADS_TMP_DIR=(str, "storage/uploads_tmp/"),
    # SIPI base URL used by the ingest worker's tile smoke test. Empty means
    # "use IIIF_HOST" — override when the worker reaches SIPI on an internal
    # hostname (e.g. http://image_server:1024/ inside Docker Compose).
    UPLOADS_SIPI_BASE_URL=(str, ""),
    UPLOADS_STALE_AFTER_DAYS=(int, 7),
    # Error-notification email (ADMINS) and outgoing mail (SMTP).
    ADMIN_EMAILS=(list, []),
    SERVER_EMAIL=(str, "root@localhost"),
    DEFAULT_FROM_EMAIL=(str, "webmaster@localhost"),
    EMAIL_BACKEND=(str, "django.core.mail.backends.console.EmailBackend"),
    EMAIL_HOST=(str, "localhost"),
    EMAIL_PORT=(int, 587),
    EMAIL_HOST_USER=(str, ""),
    EMAIL_HOST_PASSWORD=(str, ""),
    EMAIL_USE_TLS=(bool, True),
    EMAIL_TIMEOUT=(int, 10),
)

# Tests run with DEBUG off and the insecure SECRET_KEY default; the production
# guards below must not fire in that path. conftest sets USE_SQLITE_FOR_TESTS
# before django.setup(); PYTEST_CURRENT_TEST / "test" in argv cover the rest.
_RUNNING_TESTS = (
    os.environ.get("USE_SQLITE_FOR_TESTS") == "1" or "PYTEST_CURRENT_TEST" in os.environ or "test" in sys.argv
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

# Fail fast rather than silently boot production with a publicly-known signing
# key. SECRET_KEY signs sessions and password-reset tokens, so the insecure
# default ("django-insecure…") must never reach a real deployment.
if not DEBUG and not _RUNNING_TESTS and (not SECRET_KEY or SECRET_KEY.startswith("django-insecure")):
    raise ImproperlyConfigured(
        "SECRET_KEY is unset or uses the insecure default. Set a strong, unique SECRET_KEY in production."
    )

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

SESSION_COOKIE_DOMAIN = env("SESSION_COOKIE_DOMAIN")
CSRF_COOKIE_DOMAIN = env("CSRF_COOKIE_DOMAIN")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Production HTTPS hardening. nginx terminates TLS and forwards the proto via
# the header above, so SSL redirect / secure cookies / HSTS are safe to enable.
# Gated off in DEBUG and tests (no TLS there). SECURE_SSL_REDIRECT and the HSTS
# max-age are env-overridable for deployments that front TLS differently.
if not DEBUG and not _RUNNING_TESTS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
    SECURE_HSTS_SECONDS = env("SECURE_HSTS_SECONDS")
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

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
    "apps.annotations_w3c",
    "apps.iiif_presentation",
    "apps.manuscripts",
    "apps.publications",
    "apps.pages",
    "apps.worksets",
    "apps.search",
    "apps.uploads",
]

MIDDLEWARE = [
    "apps.common.middleware.RequestIDMiddleware",
    # must precede CorsMiddleware, which claims every preflight itself
    "apps.iiif_presentation.middleware.IIIFCorsPreflightMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Must follow AuthenticationMiddleware (see class docstring): resolves the
    # real DRF-authenticated user onto request.user even for requests DRF
    # itself would never authenticate (e.g. GETs under IsAuthenticatedOrReadOnly),
    # so mail_admins error-notification emails attribute errors correctly.
    "apps.common.middleware.ResolveAuthenticatedUserMiddleware",
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

# Auto-switch to isolated sqlite database while running tests. The
# USE_SQLITE_FOR_TESTS check is what makes host-run pytest work: conftest.py
# sets it before django.setup(), whereas PYTEST_CURRENT_TEST is only set by
# pytest *after* settings are imported (so it alone never triggers here).
if _RUNNING_TESTS:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / "test.db"),
        }
    }

# `default` stays in-memory (throttling/tests rely on it and must not need a
# running Redis). The `locks` alias is a Redis-backed cache used only for the
# cross-process search-reindex single-flight lock; its callers degrade
# gracefully when the backend is unavailable (e.g. host tests without Redis).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
    "locks": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL"),
        "OPTIONS": {"socket_connect_timeout": 1, "socket_timeout": 1},
    },
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
    "DEFAULT_THROTTLE_CLASSES": ()
    if DEBUG
    else (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {}
    if DEBUG
    else {
        "anon": env("DRF_THROTTLE_ANON_RATE"),
        "user": env("DRF_THROTTLE_USER_RATE"),
    },
    # Appending proxy hops in front of Django. Leave unset until the live chain is
    # measured: too low and every visitor shares one bucket.
    "NUM_PROXIES": env("DRF_NUM_PROXIES"),
    "DEFAULT_PAGINATION_CLASS": "config.pagination.BoundedLimitOffsetPagination",
    "PAGE_SIZE": 20,
    # ProtectedError → 409 (a PROTECT-blocked delete is a conflict, not a 500).
    "EXCEPTION_HANDLER": "apps.common.exceptions.drf_exception_handler",
}

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = "storage/media/"
STATIC_ROOT = BASE_DIR / "storage/staticfiles"
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755
FILE_UPLOAD_PERMISSIONS = 0o644

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Email — SMTP for outgoing mail, ADMINS for the mail_admins logging handler
# below (uncaught view exceptions get emailed to these addresses, full
# traceback and request metadata included). Defaults to the console backend
# so local dev prints mail to stdout instead of requiring real SMTP
# credentials.
ADMINS = env("ADMIN_EMAILS")
MANAGERS = ADMINS
SERVER_EMAIL = env("SERVER_EMAIL")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
EMAIL_BACKEND = env("EMAIL_BACKEND")
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = env("EMAIL_PORT")
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env("EMAIL_USE_TLS")
# smtplib blocks with no timeout by default, and logging.Handler.handle holds a
# per-handler lock — one stalled SMTP server would block every thread that hits
# an error.
EMAIL_TIMEOUT = env("EMAIL_TIMEOUT")
# mail_admins()/mail_managers() prefix every subject with this; default is
# literally "[Django] " which tells you nothing when you run more than one
# Django site.
EMAIL_SUBJECT_PREFIX = f"[{SITE_NAME}] "

# Logging — switch to JSON formatter via LOG_FORMAT=json.
# Default 'text' for human-readable dev output.
LOG_FORMAT = env("LOG_FORMAT", default="text")

# Opt-in size-rotated file logging alongside the console stream. The Dockerfile
# creates /var/log/app owned by the app user, so this needs no per-environment
# provisioning; outside a container it usually isn't writable, so degrade to
# console rather than take down django.setup() over an optional feature.
LOG_FILE_PATH = "/var/log/app/app.log"
_FILE_LOGGING_ENABLED = env("LOG_IN_FILE")
if _FILE_LOGGING_ENABLED:
    try:
        os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
    except OSError as exc:
        print(f"LOG_IN_FILE is set but {LOG_FILE_PATH} is unusable ({exc}); logging to console only", file=sys.stderr)
        _FILE_LOGGING_ENABLED = False

_log_handlers = ["console", "file"] if _FILE_LOGGING_ENABLED else ["console"]

_text_format = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s"
_json_format = "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s %(filename)s %(lineno)d"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "apps.common.middleware.get_request_id_filter"},
    },
    "formatters": {
        "text": {"format": _text_format},
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "format": _json_format,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if LOG_FORMAT == "json" else "text",
            "filters": ["request_id"],
        },
        **(
            {
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": LOG_FILE_PATH,
                    "maxBytes": 10 * 1024 * 1024,  # 10 MB per file
                    "backupCount": 5,
                    # Open on first record: an existing-but-unwritable file then
                    # degrades to a stderr handleError instead of failing boot.
                    "delay": True,
                    "formatter": "json" if LOG_FORMAT == "json" else "text",
                    "filters": ["request_id"],
                }
            }
            if _FILE_LOGGING_ENABLED
            else {}
        ),
        # Emails ADMINS the traceback + request metadata (path, headers,
        # GET/POST, user) for uncaught view exceptions, regardless of DEBUG.
        # Send failures are swallowed (fail_silently, Django default) so a
        # broken SMTP config can't take down error handling.
        "mail_admins": {
            "level": "ERROR",
            "class": "apps.common.error_notifications.AdminNotificationEmailHandler",
            "include_html": True,
            "reporter_class": "apps.common.error_notifications.AdminNotificationReporter",
        },
    },
    "loggers": {
        "django": {
            "handlers": _log_handlers,
            "level": "INFO",
        },
        # Declared explicitly (rather than left to Django's merged defaults)
        # so it's clear uncaught request exceptions both log to console and
        # email ADMINS. propagate=False avoids a duplicate console line via
        # the "django" logger above.
        "django.request": {
            "handlers": _log_handlers + ["mail_admins"],
            "level": "ERROR",
            "propagate": False,
        },
        # Application logs live under the `apps.*` namespace. Without this they
        # propagate to the unconfigured root logger and fall back to Python's
        # lastResort handler (stderr, WARNING+, no request_id/formatter).
        # mail_admins here also covers logger.exception() calls made outside
        # the request cycle (e.g. search reindexing, Celery tasks).
        "apps": {
            "handlers": _log_handlers + ["mail_admins"],
            "level": env("APP_LOG_LEVEL"),
            "propagate": False,
        },
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

# Chunked image uploads (apps.uploads). The tmp dir lives OUTSIDE MEDIA_ROOT
# on purpose: SIPI serves MEDIA_ROOT by literal path, and a partial chunk file
# must never be servable.
UPLOADS_MAX_BYTES = env("UPLOADS_MAX_BYTES")
UPLOADS_CHUNK_SIZE = env("UPLOADS_CHUNK_SIZE")
UPLOADS_TMP_DIR = env("UPLOADS_TMP_DIR")
UPLOADS_SIPI_BASE_URL = env("UPLOADS_SIPI_BASE_URL") or IIIF_HOST
UPLOADS_STALE_AFTER_DAYS = env("UPLOADS_STALE_AFTER_DAYS")

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
