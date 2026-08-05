"""Tests for the sanity-checks service (apps.common.services.sanity_checks) and endpoint.

Pinned behaviour:
  - get_pending_migrations reflects the migration executor's plan (empty once
    a test DB is fully migrated, which pytest-django guarantees)
  - each service-reachability check reports {"ok": bool, "detail": ...} and
    never raises, even when the dependency is unreachable/misconfigured
  - smtp_configured is False for Django's untouched default ("localhost") and
    True once EMAIL_HOST is actually overridden
  - get_database_size_bytes is None on non-Postgres backends (sqlite in tests)
  - media_root resolves a relative MEDIA_ROOT against BASE_DIR
  - the endpoint is superuser-gated and thin (delegates to run_sanity_checks)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import override_settings
import pytest

from apps.common.services import sanity_checks as sc

URL = "/api/v1/management/common/sanity-checks/"


class TestGetPendingMigrations:
    @pytest.mark.django_db
    def test_no_pending_migrations_once_db_is_migrated(self):
        # pytest-django fully migrates the test database, so the executor's
        # plan against current heads should be empty.
        assert sc.get_pending_migrations() == []


class TestCheckDatabase:
    @pytest.mark.django_db
    def test_ok_when_connection_available(self):
        result = sc.check_database()
        assert result == {"ok": True, "detail": None}

    def test_reports_failure_without_raising(self):
        with patch("apps.common.services.sanity_checks.connection") as connection_mock:
            connection_mock.ensure_connection.side_effect = RuntimeError("boom")
            result = sc.check_database()
        assert result["ok"] is False
        assert "boom" in result["detail"]


class TestCheckRedis:
    def test_ok_when_cache_reachable(self):
        cache_mock = MagicMock()
        with patch("apps.common.services.sanity_checks.caches", {sc._REDIS_CACHE_ALIAS: cache_mock}):
            result = sc.check_redis()
        assert result == {"ok": True, "detail": None}
        cache_mock.set.assert_called_once()

    def test_reports_failure_without_raising(self):
        cache_mock = MagicMock()
        cache_mock.set.side_effect = ConnectionError("no redis")
        with patch("apps.common.services.sanity_checks.caches", {sc._REDIS_CACHE_ALIAS: cache_mock}):
            result = sc.check_redis()
        assert result["ok"] is False
        assert "no redis" in result["detail"]


class TestCheckMeilisearch:
    def test_ok_when_healthy(self):
        client_mock = MagicMock()
        with patch("meilisearch.Client", return_value=client_mock):
            result = sc.check_meilisearch()
        assert result == {"ok": True, "detail": None}
        client_mock.health.assert_called_once()

    def test_not_ok_when_communication_error(self):
        from meilisearch.errors import MeilisearchCommunicationError

        client_mock = MagicMock()
        client_mock.health.side_effect = MeilisearchCommunicationError("unreachable")
        with patch("meilisearch.Client", return_value=client_mock):
            result = sc.check_meilisearch()
        assert result["ok"] is False
        assert result["detail"]

    def test_reports_failure_without_raising(self):
        with patch("meilisearch.Client", side_effect=RuntimeError("down")):
            result = sc.check_meilisearch()
        assert result["ok"] is False
        assert "down" in result["detail"]


class TestCheckCeleryBroker:
    def test_ok_when_broker_reachable(self):
        connection_ctx = MagicMock()
        connection_ctx.__enter__.return_value = connection_ctx
        celery_app_mock = MagicMock()
        celery_app_mock.connection.return_value = connection_ctx
        with patch("config.celery.app", celery_app_mock):
            result = sc.check_celery_broker()
        assert result == {"ok": True, "detail": None}
        connection_ctx.ensure_connection.assert_called_once()

    def test_reports_failure_without_raising(self):
        celery_app_mock = MagicMock()
        celery_app_mock.connection.side_effect = ConnectionError("no broker")
        with patch("config.celery.app", celery_app_mock):
            result = sc.check_celery_broker()
        assert result["ok"] is False
        assert "no broker" in result["detail"]


class TestSmtpConfigured:
    @override_settings(EMAIL_HOST="localhost")
    def test_false_for_django_default(self):
        assert sc.smtp_configured() is False

    @override_settings(EMAIL_HOST="")
    def test_false_when_empty(self):
        assert sc.smtp_configured() is False

    @override_settings(EMAIL_HOST="smtp.example.com")
    def test_true_when_overridden(self):
        assert sc.smtp_configured() is True


class TestGetDatabaseSizeBytes:
    @pytest.mark.django_db
    def test_none_on_non_postgres_backend(self):
        # Explicitly mocked rather than relying on the active test DB vendor:
        # integration-tests runs this suite against real Postgres (only local/
        # unit-tests runs use sqlite via conftest.py's USE_SQLITE_FOR_TESTS).
        connection_mock = MagicMock(vendor="sqlite")
        with patch("apps.common.services.sanity_checks.connection", connection_mock):
            assert sc.get_database_size_bytes() is None

    def test_queries_pg_database_size_on_postgres(self):
        cursor_mock = MagicMock()
        cursor_mock.fetchone.return_value = (123456,)
        cursor_cm = MagicMock()
        cursor_cm.__enter__.return_value = cursor_mock
        connection_mock = MagicMock(vendor="postgresql")
        connection_mock.cursor.return_value = cursor_cm
        with patch("apps.common.services.sanity_checks.connection", connection_mock):
            assert sc.get_database_size_bytes() == 123456
        cursor_mock.execute.assert_called_once_with("SELECT pg_database_size(current_database())")


class TestMediaRoot:
    def test_relative_media_root_resolved_against_base_dir(self):
        with override_settings(BASE_DIR=Path("/srv/app"), MEDIA_ROOT="storage/media/"):
            assert sc.media_root() == Path("/srv/app/storage/media")

    def test_absolute_media_root_left_as_is(self):
        with override_settings(MEDIA_ROOT="/srv/other/media"):
            assert sc.media_root() == Path("/srv/other/media")


class TestDirectorySizeAndWritability:
    def test_get_directory_size_bytes_sums_files_recursively(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"1234")
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "b.txt").write_bytes(b"123")
        assert sc.get_directory_size_bytes(tmp_path) == 7

    def test_get_directory_size_bytes_missing_path_is_zero(self, tmp_path):
        assert sc.get_directory_size_bytes(tmp_path / "does-not-exist") == 0

    def test_is_path_writable_true_for_writable_dir(self, tmp_path):
        assert sc.is_path_writable(tmp_path) is True

    def test_is_path_writable_false_for_missing_path(self, tmp_path):
        assert sc.is_path_writable(tmp_path / "nope") is False


class TestRunSanityChecks:
    @pytest.mark.django_db
    def test_aggregates_all_signals(self):
        with (
            patch("apps.common.services.sanity_checks.get_pending_migrations", return_value=["app.0002_x"]),
            patch("apps.common.services.sanity_checks.check_database", return_value={"ok": True, "detail": None}),
            patch("apps.common.services.sanity_checks.check_redis", return_value={"ok": True, "detail": None}),
            patch("apps.common.services.sanity_checks.check_meilisearch", return_value={"ok": True, "detail": None}),
            patch("apps.common.services.sanity_checks.check_celery_broker", return_value={"ok": True, "detail": None}),
            patch("apps.common.services.sanity_checks.smtp_configured", return_value=True),
            patch("apps.common.services.sanity_checks.get_database_size_bytes", return_value=42),
            patch("apps.common.services.sanity_checks.get_directory_size_bytes", return_value=99),
            patch("apps.common.services.sanity_checks.is_path_writable", return_value=True),
        ):
            result = sc.run_sanity_checks()

        assert result["migrations"] == {"has_pending": True, "pending": ["app.0002_x"]}
        assert result["services"]["database"] == {"ok": True, "detail": None}
        assert result["services"]["redis"] == {"ok": True, "detail": None}
        assert result["services"]["meilisearch"] == {"ok": True, "detail": None}
        assert result["services"]["celery_broker"] == {"ok": True, "detail": None}
        assert result["email"] == {"smtp_configured": True}
        assert result["database_size_bytes"] == 42
        assert result["media"]["size_bytes"] == 99
        assert result["media"]["writable"] is True
        assert result["logs"]["writable"] is True


@pytest.mark.django_db
class TestSanityChecksView:
    def test_anonymous_is_rejected(self, api_client):
        response = api_client.get(URL)
        assert response.status_code in (401, 403)

    def test_regular_user_is_forbidden(self, authenticated_client):
        response = authenticated_client.get(URL)
        assert response.status_code == 403

    def test_superuser_gets_report(self, management_client):
        canned = {"migrations": {"has_pending": False, "pending": []}}
        with patch("apps.common.views.run_sanity_checks", return_value=canned):
            response = management_client.get(URL)
        assert response.status_code == 200
        assert response.data == canned

    def test_view_delegates_to_service_without_inline_logic(self, management_client):
        # The view is transport-only: it must call the service, not recompute
        # any of the checks itself.
        with patch("apps.common.views.run_sanity_checks") as run_mock:
            run_mock.return_value = {}
            management_client.get(URL)
        run_mock.assert_called_once_with()
