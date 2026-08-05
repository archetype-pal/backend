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
from typing import Any

from django.conf import settings
from django.core.cache import caches
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

logger = logging.getLogger(__name__)

# The Redis-backed cache alias used for the cross-process reindex lock (see
# apps.search.services.reindex_lock) — reused here as a cheap Redis reachability
# probe rather than opening a second connection with different settings.
_REDIS_CACHE_ALIAS = "locks"
_REDIS_PROBE_KEY = "common:sanity-check:probe"

# Django's global default settings (django.conf.global_settings) already set
# EMAIL_HOST="localhost" and EMAIL_BACKEND to the SMTP backend even when a
# project never touches email settings at all — which is exactly this
# project's current state (no EMAIL_* settings in config/settings.py). A naive
# `bool(EMAIL_HOST)` would therefore always report True. Requiring the value to
# differ from the untouched default lets an unconfigured install report False.
_DJANGO_DEFAULT_EMAIL_HOST = "localhost"


def get_pending_migrations() -> list[str]:
    """Return `["app_label.migration_name", ...]` for unapplied migrations.

    Uses the same executor Django's own `migrate --check`/`showmigrations`
    commands build on, rather than shelling out and parsing text output.
    """
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return [f"{migration.app_label}.{migration.name}" for migration, _backwards in plan]


def check_database() -> dict[str, Any]:
    try:
        connection.ensure_connection()
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
        from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

        url = getattr(settings, "MEILISEARCH_URL", "http://localhost:7700")
        api_key = getattr(settings, "MEILISEARCH_API_KEY", None) or None
        Client(url=url, api_key=api_key).health()
        return {"ok": True, "detail": None}
    except (MeilisearchApiError, MeilisearchCommunicationError, OSError, ConnectionError) as exc:  # fmt: skip
        return {"ok": False, "detail": str(exc)}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def check_celery_broker() -> dict[str, Any]:
    """Reachability check for the Celery broker used by the `celery` compose service."""
    try:
        from config.celery import app as celery_app

        with celery_app.connection() as conn:
            conn.ensure_connection(max_retries=1, timeout=2)
        return {"ok": True, "detail": None}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}


def smtp_configured() -> bool:
    """Best-effort signal that SMTP looks configured — not a send test (that's a separate issue)."""
    host = getattr(settings, "EMAIL_HOST", "")
    return bool(host) and host != _DJANGO_DEFAULT_EMAIL_HOST


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


def log_directory() -> Path:
    """Resolve the directory sanity checks treat as "the log directory".

    This project logs to stdout only (see LOGGING in config/settings.py —
    only a console StreamHandler is configured, no file handler), so there is
    no dedicated on-disk log directory. BASE_DIR is used as the closest
    stand-in: it's where a file handler would write to if one were ever
    added, and it must be writable anyway (e.g. for the local sqlite dev DB).
    """
    return Path(settings.BASE_DIR)


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


def is_path_writable(path: Path) -> bool:
    return path.exists() and os.access(path, os.W_OK)


def run_sanity_checks() -> dict[str, Any]:
    """Aggregate all sanity-check signals into a single JSON-serializable dict."""
    pending_migrations = get_pending_migrations()
    media_path = media_root()
    logs_path = log_directory()

    return {
        "migrations": {
            "has_pending": bool(pending_migrations),
            "pending": pending_migrations,
        },
        "services": {
            "database": check_database(),
            "redis": check_redis(),
            "meilisearch": check_meilisearch(),
            "celery_broker": check_celery_broker(),
        },
        "email": {
            "smtp_configured": smtp_configured(),
        },
        "database_size_bytes": get_database_size_bytes(),
        "media": {
            "path": str(media_path),
            "size_bytes": get_directory_size_bytes(media_path),
            "writable": is_path_writable(media_path),
        },
        "logs": {
            "path": str(logs_path),
            "writable": is_path_writable(logs_path),
        },
    }
