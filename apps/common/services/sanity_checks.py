"""Operational sanity checks for the superuser-gated `/management/` API.

Aggregates a handful of "is the deployment healthy" signals that used to be
eyeballed manually: pending migrations, dependent-service reachability, SMTP
configuration, storage usage, and filesystem permissions. Kept here (rather
than inline in the view) per CONTRIBUTING's views-are-transport-only rule.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from smtplib import SMTPException
from typing import Any

from django.conf import settings
from django.core.cache import caches
from django.core.mail import send_mail
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

logger = logging.getLogger(__name__)

# The Redis-backed cache alias used for the cross-process reindex lock (see
# apps.search.services.reindex_lock) — reused here as a cheap Redis reachability
# probe rather than opening a second connection with different settings.
_REDIS_CACHE_ALIAS = "locks"
_REDIS_PROBE_KEY = "common:sanity-check:probe"

# The walk stats every file under MEDIA_ROOT — tens of thousands on a real corpus.
_MEDIA_SIZE_CACHE_KEY = "common:sanity-check:media-size-bytes"
_MEDIA_SIZE_CACHE_TTL_SECONDS = 60

# The endpoint is synchronous, so every probe must be bounded.
_MEILISEARCH_TIMEOUT_SECONDS = 2
_CELERY_BROKER_TIMEOUT_SECONDS = 2
_CELERY_PING_TIMEOUT_SECONDS = 1

# config/settings.py defaults EMAIL_BACKEND to the console backend, so a deployment
# that sets only EMAIL_HOST/USER/PASSWORD still prints mail to stdout.
_DJANGO_DEFAULT_EMAIL_HOST = "localhost"


def get_pending_migrations() -> list[str]:
    """Return `["app_label.migration_name", ...]` for unapplied migrations.

    Uses the same executor Django's own `migrate --check`/`showmigrations`
    commands build on, rather than shelling out and parsing text output.
    """
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return [f"{migration.app_label}.{migration.name}" for migration, _backwards in plan]


def check_migrations() -> dict[str, Any]:
    """Pending-migration state, with an explicit unknown.

    A broken migration graph fails here against a healthy database, so it must
    not report `has_pending: true` — that sends an operator to run `just migrate`
    for nothing.
    """
    try:
        pending = get_pending_migrations()
    except Exception as exc:
        logger.warning("Failed to compute pending migrations for sanity checks", exc_info=exc)
        return {"ok": False, "has_pending": None, "pending": [], "detail": str(exc)}
    return {"ok": True, "has_pending": bool(pending), "pending": pending, "detail": None}


def check_database() -> dict[str, Any]:
    """Reachability check for the database.

    Runs a real query: connections persist across requests (`conn_max_age=600`)
    and `ensure_connection()` does not detect an already-dead socket.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return {"ok": True, "detail": None}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def check_redis() -> dict[str, Any]:
    """Reachability check for the Redis-backed `locks` cache (see compose.yaml's `redis` service)."""
    try:
        cache = caches[_REDIS_CACHE_ALIAS]
        cache.set(_REDIS_PROBE_KEY, "1", timeout=5)
        cache.get(_REDIS_PROBE_KEY)
        return {"ok": True, "detail": None}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def check_meilisearch() -> dict[str, Any]:
    """Reachability check for the `meilisearch` compose service.

    Built directly from settings rather than importing `apps.search` (e.g. its
    `SearchAdminService.check_meilisearch_health()`, which does the same
    thing): `common` is the dependency-free foundation app per
    `scripts/check_architecture_boundaries.py`, and every other app depends on
    it, never the reverse.
    """
    try:
        from meilisearch import Client

        api_key = settings.MEILISEARCH_API_KEY or None
        Client(url=settings.MEILISEARCH_URL, api_key=api_key, timeout=_MEILISEARCH_TIMEOUT_SECONDS).health()
        return {"ok": True, "detail": None}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def check_celery_broker() -> dict[str, Any]:
    """Reachability check for the Celery broker used by the `celery` compose service."""
    try:
        from config.celery import app as celery_app

        with celery_app.connection() as conn:
            conn.ensure_connection(max_retries=1, timeout=_CELERY_BROKER_TIMEOUT_SECONDS)
        return {"ok": True, "detail": None}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def check_celery_workers() -> dict[str, Any]:
    """Liveness of the Celery consumers themselves.

    The broker probe cannot see a crash-looping worker — it is the same Redis
    server as the `locks` cache, so it goes green while tasks pile up unconsumed.
    """
    try:
        from config.celery import app as celery_app

        replies = celery_app.control.ping(timeout=_CELERY_PING_TIMEOUT_SECONDS) or []
        return {
            "ok": bool(replies),
            "workers": len(replies),
            "detail": None if replies else "No Celery workers responded to ping.",
        }
    except Exception as exc:
        return {"ok": False, "workers": 0, "detail": str(exc)}


def smtp_configured() -> bool:
    """Best-effort signal that outgoing mail would leave the box — not a send test."""
    host = getattr(settings, "EMAIL_HOST", "")
    return bool(host) and host != _DJANGO_DEFAULT_EMAIL_HOST and "smtp" in settings.EMAIL_BACKEND.lower()


def send_test_email() -> dict[str, Any]:
    """Send a one-off test email to ADMIN_EMAILS to verify SMTP delivery actually works.

    Callers must check `smtp_configured()` first — this makes no such check itself
    and will happily (and pointlessly) attempt delivery via Django's unconfigured
    "localhost" default otherwise.

    Unlike check_database/check_redis/check_meilisearch/check_celery_broker above,
    this deliberately does *not* catch a bare `Exception`: those checks report on
    dependencies outside our code, so any failure there is a legitimate "not ok".
    Here, only smtplib's own exception hierarchy and connection-level OSErrors
    (e.g. connection refused, DNS failure, timeout) are treated as an SMTP
    delivery problem — a bug in this function or its caller should raise and be
    surfaced as a 500, not get reported to the superuser as "SMTP is broken".
    """
    recipients = list(settings.ADMINS)
    if not recipients:
        return {"sent": False, "detail": "No ADMIN_EMAILS configured to send a test email to."}

    try:
        send_mail(
            subject="Archetype V3 — test email",
            message=(
                "This is a test email sent from the sanity-checks endpoint to confirm "
                "that outgoing SMTP delivery is working."
            ),
            from_email=None,
            recipient_list=recipients,
            fail_silently=False,
        )
    except (SMTPException, OSError) as exc:
        logger.warning("Test email to %s failed to send: %s", recipients, exc)
        return {"sent": False, "detail": str(exc)}

    return {"sent": True, "detail": f"Test email sent to {', '.join(recipients)}."}


def get_database_size_bytes() -> int | None:
    """Postgres-only: `pg_database_size(current_database())`. None on other backends (e.g. sqlite in tests)."""
    if connection.vendor != "postgresql":
        return None
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        row = cursor.fetchone()
        return int(row[0]) if row else None


def media_root() -> Path:
    """Resolve the actual on-disk media directory.

    AGENTS.md documents "Django media is file-system based (storage/media)"
    and manuscripts/publications ImageField/IIIFField uploads (e.g.
    HistoricalItem.image, CarouselItem.image) all go through the default
    `FileSystemStorage` at MEDIA_ROOT — confirmed by compose.yaml mounting
    `./storage/media` into the `image_server` (SIPI) container. MEDIA_ROOT is
    configured as a relative path ("storage/media/"), so resolve it against
    BASE_DIR rather than assuming it's already absolute.
    """
    root = Path(settings.MEDIA_ROOT)
    if not root.is_absolute():
        root = Path(settings.BASE_DIR) / root
    return root


def log_file_path() -> Path | None:
    """Path written to by the first file handler in `settings.LOGGING`, if any.

    This project logs to stdout, so there is normally no log file to report on.
    """
    handlers = (getattr(settings, "LOGGING", None) or {}).get("handlers") or {}
    for handler in handlers.values():
        if not isinstance(handler, dict):
            continue
        filename = handler.get("filename")
        if filename and str(handler.get("class", "")).endswith("FileHandler"):
            return Path(filename)
    return None


def check_logs() -> dict[str, Any]:
    """Report on the configured log file, or say plainly that there isn't one."""
    path = log_file_path()
    if path is None:
        return {"configured": False, "path": None, "writable": None}
    target = path if path.exists() else path.parent
    return {"configured": True, "path": str(path), "writable": is_path_writable(target)}


def get_directory_size_bytes(path: Path) -> int:
    """Sum of file sizes under `path`, recursively. Returns 0 if the path doesn't exist."""
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                continue
    return total


def get_media_size_bytes() -> int:
    """Size of MEDIA_ROOT, with a short-lived cache in front of the walk."""
    try:
        cache = caches[_REDIS_CACHE_ALIAS]
        cached = cache.get(_MEDIA_SIZE_CACHE_KEY)
        if cached is not None:
            return int(cached)
        size = get_directory_size_bytes(media_root())
        cache.set(_MEDIA_SIZE_CACHE_KEY, size, timeout=_MEDIA_SIZE_CACHE_TTL_SECONDS)
        return size
    except Exception as exc:
        logger.warning("Media-size cache unavailable, walking uncached", exc_info=exc)
        return get_directory_size_bytes(media_root())


def is_path_writable(path: Path) -> bool:
    return path.exists() and os.access(path, os.W_OK)


def run_sanity_checks() -> dict[str, Any]:
    """Aggregate all sanity-check signals into a single JSON-serializable dict."""
    media_path = media_root()

    try:
        database_size_bytes = get_database_size_bytes()
    except Exception as exc:
        logger.warning("Failed to compute database size for sanity checks", exc_info=exc)
        database_size_bytes = None

    return {
        "migrations": check_migrations(),
        "services": {
            "database": check_database(),
            "redis": check_redis(),
            "meilisearch": check_meilisearch(),
            "celery_broker": check_celery_broker(),
            "celery_workers": check_celery_workers(),
        },
        "email": {
            "backend": settings.EMAIL_BACKEND,
            "smtp_configured": smtp_configured(),
        },
        "database": {
            "size_bytes": database_size_bytes,
        },
        "media": {
            "path": str(media_path),
            "size_bytes": get_media_size_bytes(),
            "writable": is_path_writable(media_path),
        },
        "logs": check_logs(),
    }
