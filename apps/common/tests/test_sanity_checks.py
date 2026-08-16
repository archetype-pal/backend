"""Tests for the sanity-checks service (apps.common.services.sanity_checks) and endpoint.

Pinned behaviour:
  - get_pending_migrations reflects the migration executor's plan (empty once
    a test DB is fully migrated, which pytest-django guarantees)
  - a migration plan that can't be computed reports unknown, never "pending"
  - each service-reachability check reports {"ok": bool, "detail": ...} and
    never raises, even when the dependency is unreachable/misconfigured
  - smtp_configured is False for Django's untouched default ("localhost") and
    for a backend that only prints, True once both are real
  - get_database_size_bytes is None on non-Postgres backends (sqlite in tests)
  - media_root resolves a relative MEDIA_ROOT against BASE_DIR
  - the endpoint is superuser-gated, thin (delegates to run_sanity_checks) and
    ships exactly the field set schema.yaml publishes
  - send_test_email goes out via django.core.mail.mail_admins (SERVER_EMAIL
    sender, subject prefix, settings.ADMINS recipients) and reports
    {"sent": bool, "detail": ...}, only swallowing OSError delivery failures
  - the test-email endpoint is superuser-gated, answers 400 without sending when
    SMTP isn't configured or ADMINS is empty, and reserves 502 for a configured
    relay refusing the message
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from smtplib import SMTPException
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import override_settings
import pytest
import yaml

from apps.common.services import sanity_checks as sc

URL = "/api/v1/management/common/sanity-checks/"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.yaml"
TEST_EMAIL_URL = "/api/v1/management/common/sanity-checks/test-email/"

CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


def _cursor_connection(**kwargs) -> MagicMock:
    """A `connection` double whose `cursor()` context manager yields a recording cursor."""
    cursor = MagicMock()
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    connection = MagicMock(**kwargs)
    connection.cursor.return_value = cursor_cm
    return connection


class TestGetPendingMigrations:
    @pytest.mark.django_db
    def test_no_pending_migrations_once_db_is_migrated(self):
        # pytest-django fully migrates the test database, so the executor's
        # plan against current heads should be empty.
        assert sc.get_pending_migrations() == []


class TestCheckMigrations:
    def test_ok_when_nothing_pending(self):
        with patch("apps.common.services.sanity_checks.get_pending_migrations", return_value=[]):
            assert sc.check_migrations() == {"ok": True, "has_pending": False, "pending": [], "detail": None}

    def test_reports_pending_names(self):
        with patch("apps.common.services.sanity_checks.get_pending_migrations", return_value=["app.0002_x"]):
            result = sc.check_migrations()
        assert result == {"ok": True, "has_pending": True, "pending": ["app.0002_x"], "detail": None}

    def test_broken_graph_is_unknown_not_pending(self):
        # A NodeNotFoundError/BadMigrationError happens against a perfectly
        # healthy database; reporting has_pending=true would send an operator
        # to run `just migrate` for nothing.
        with patch(
            "apps.common.services.sanity_checks.get_pending_migrations",
            side_effect=RuntimeError("bad migration graph"),
        ):
            result = sc.check_migrations()
        assert result["ok"] is False
        assert result["has_pending"] is None
        assert result["pending"] == []
        assert "bad migration graph" in result["detail"]


class TestCheckDatabase:
    @pytest.mark.django_db
    def test_ok_when_connection_available(self):
        result = sc.check_database()
        assert result == {"ok": True, "detail": None}

    def test_executes_a_query(self):
        # ensure_connection() doesn't ping a persistent connection; only opening
        # a cursor runs the health check that reaps a dead socket.
        connection_mock = _cursor_connection()
        with patch("apps.common.services.sanity_checks.connection", connection_mock):
            assert sc.check_database() == {"ok": True, "detail": None}
        connection_mock.cursor.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT 1")

    def test_reports_failure_without_raising(self):
        with patch("apps.common.services.sanity_checks.connection") as connection_mock:
            connection_mock.cursor.side_effect = RuntimeError("boom")
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

    def test_probe_is_time_bounded(self):
        # Without a timeout the SDK blocks forever on a Meilisearch that accepts
        # the connection and never answers, hanging the whole endpoint.
        with patch("meilisearch.Client") as client_cls:
            sc.check_meilisearch()
        assert client_cls.call_args.kwargs["timeout"] == sc._MEILISEARCH_TIMEOUT_SECONDS

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


class TestCheckCeleryWorkers:
    def test_counts_responding_workers(self):
        celery_app_mock = MagicMock()
        celery_app_mock.control.ping.return_value = [{"celery@a": {"ok": "pong"}}, {"celery@b": {"ok": "pong"}}]
        with patch("config.celery.app", celery_app_mock):
            result = sc.check_celery_workers()
        assert result == {"ok": True, "workers": 2, "detail": None}
        assert celery_app_mock.control.ping.call_args.kwargs["timeout"] == sc._CELERY_PING_TIMEOUT_SECONDS

    def test_not_ok_when_no_worker_answers(self):
        celery_app_mock = MagicMock()
        celery_app_mock.control.ping.return_value = []
        with patch("config.celery.app", celery_app_mock):
            result = sc.check_celery_workers()
        assert result["ok"] is False
        assert result["workers"] == 0
        assert result["detail"]

    def test_reports_failure_without_raising(self):
        celery_app_mock = MagicMock()
        celery_app_mock.control.ping.side_effect = ConnectionError("no broker")
        with patch("config.celery.app", celery_app_mock):
            result = sc.check_celery_workers()
        assert result == {"ok": False, "workers": 0, "detail": "no broker"}


class TestSmtpConfigured:
    @override_settings(EMAIL_HOST="localhost", EMAIL_BACKEND=SMTP_BACKEND)
    def test_false_for_django_default_host(self):
        assert sc.smtp_configured() is False

    @override_settings(EMAIL_HOST="", EMAIL_BACKEND=SMTP_BACKEND)
    def test_false_when_host_empty(self):
        assert sc.smtp_configured() is False

    @override_settings(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND=CONSOLE_BACKEND)
    def test_false_when_backend_only_prints_to_stdout(self):
        # The console backend is config/settings.py's shipped default, so this is
        # the case that would otherwise make a green "sent" mean "printed".
        assert sc.smtp_configured() is False

    @override_settings(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND=SMTP_BACKEND)
    def test_true_when_host_and_backend_are_real(self):
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
        connection_mock = _cursor_connection(vendor="postgresql")
        cursor_mock = connection_mock.cursor.return_value.__enter__.return_value
        cursor_mock.fetchone.return_value = (123456,)
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


def _logging_config(**handlers) -> dict:
    """A dictConfig Django will accept — override_settings(LOGGING=...) re-applies it for real."""
    return {"version": 1, "disable_existing_loggers": False, "handlers": handlers}


class TestLogs:
    def test_not_configured_without_a_file_handler(self):
        # This project's own LOGGING: console + mail_admins, nothing on disk.
        with override_settings(LOGGING=_logging_config(console={"class": "logging.StreamHandler"})):
            assert sc.log_file_path() is None
            assert sc.check_logs() == {"configured": False, "path": None, "writable": None}

    def test_reports_the_file_handler_target(self, tmp_path):
        log_file = tmp_path / "app.log"
        log_file.write_text("")
        config = _logging_config(
            console={"class": "logging.StreamHandler"},
            file={"class": "logging.handlers.WatchedFileHandler", "filename": str(log_file)},
        )
        with override_settings(LOGGING=config):
            assert sc.check_logs() == {"configured": True, "path": str(log_file), "writable": True}

    def test_falls_back_to_the_parent_directory_when_the_file_is_not_created_yet(self, tmp_path):
        log_file = tmp_path / "not-yet.log"
        config = _logging_config(file={"class": "logging.FileHandler", "filename": str(log_file), "delay": True})
        with override_settings(LOGGING=config):
            log_file.unlink(missing_ok=True)
            result = sc.check_logs()
        assert result == {"configured": True, "path": str(log_file), "writable": True}


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


class TestGetMediaSizeBytes:
    def test_serves_a_cached_size_without_walking(self):
        cache_mock = MagicMock()
        cache_mock.get.return_value = 4242
        with (
            patch("apps.common.services.sanity_checks.caches", {sc._REDIS_CACHE_ALIAS: cache_mock}),
            patch("apps.common.services.sanity_checks.get_directory_size_bytes") as walk_mock,
        ):
            assert sc.get_media_size_bytes() == 4242
        walk_mock.assert_not_called()

    def test_caches_a_freshly_computed_size(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"12345")
        cache_mock = MagicMock()
        cache_mock.get.return_value = None
        with (
            patch("apps.common.services.sanity_checks.caches", {sc._REDIS_CACHE_ALIAS: cache_mock}),
            patch("apps.common.services.sanity_checks.media_root", return_value=tmp_path),
        ):
            assert sc.get_media_size_bytes() == 5
        cache_mock.set.assert_called_once_with(sc._MEDIA_SIZE_CACHE_KEY, 5, timeout=sc._MEDIA_SIZE_CACHE_TTL_SECONDS)

    def test_degrades_to_an_uncached_walk_when_the_backend_is_down(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"12")
        cache_mock = MagicMock()
        cache_mock.get.side_effect = ConnectionError("no redis")
        with (
            patch("apps.common.services.sanity_checks.caches", {sc._REDIS_CACHE_ALIAS: cache_mock}),
            patch("apps.common.services.sanity_checks.media_root", return_value=tmp_path),
        ):
            assert sc.get_media_size_bytes() == 2


@contextmanager
def _stubbed_probes():
    """Stub the dependency probes — otherwise every run_sanity_checks() call waits on real sockets."""
    with (
        patch("apps.common.services.sanity_checks.check_database", return_value={"ok": True, "detail": None}),
        patch("apps.common.services.sanity_checks.check_redis", return_value={"ok": True, "detail": None}),
        patch("apps.common.services.sanity_checks.check_meilisearch", return_value={"ok": True, "detail": None}),
        patch("apps.common.services.sanity_checks.check_celery_broker", return_value={"ok": True, "detail": None}),
        patch(
            "apps.common.services.sanity_checks.check_celery_workers",
            return_value={"ok": True, "workers": 1, "detail": None},
        ),
        patch("apps.common.services.sanity_checks.get_media_size_bytes", return_value=99),
    ):
        yield


class TestRunSanityChecks:
    @pytest.mark.django_db
    @override_settings(EMAIL_BACKEND=SMTP_BACKEND)
    def test_aggregates_all_signals(self):
        with (
            _stubbed_probes(),
            patch("apps.common.services.sanity_checks.get_pending_migrations", return_value=["app.0002_x"]),
            patch("apps.common.services.sanity_checks.smtp_configured", return_value=True),
            patch("apps.common.services.sanity_checks.get_database_size_bytes", return_value=42),
            patch("apps.common.services.sanity_checks.is_path_writable", return_value=True),
        ):
            result = sc.run_sanity_checks()

        assert result["migrations"] == {
            "ok": True,
            "has_pending": True,
            "pending": ["app.0002_x"],
            "detail": None,
        }
        assert result["services"]["database"] == {"ok": True, "detail": None}
        assert result["services"]["redis"] == {"ok": True, "detail": None}
        assert result["services"]["meilisearch"] == {"ok": True, "detail": None}
        assert result["services"]["celery_broker"] == {"ok": True, "detail": None}
        assert result["services"]["celery_workers"] == {"ok": True, "workers": 1, "detail": None}
        assert result["email"] == {"backend": SMTP_BACKEND, "smtp_configured": True}
        assert result["database"] == {"size_bytes": 42}
        assert result["media"]["path"] == str(sc.media_root())
        assert result["media"]["size_bytes"] == 99
        assert result["media"]["writable"] is True
        assert result["logs"]["configured"] is False
        assert result["logs"]["path"] is None

    @pytest.mark.django_db
    def test_unavailable_migration_plan_does_not_read_as_pending(self):
        with (
            _stubbed_probes(),
            patch(
                "apps.common.services.sanity_checks.get_pending_migrations",
                side_effect=RuntimeError("NodeNotFoundError"),
            ),
        ):
            result = sc.run_sanity_checks()
        assert result["migrations"]["ok"] is False
        assert result["migrations"]["has_pending"] is None
        assert result["migrations"]["pending"] == []
        assert "NodeNotFoundError" in result["migrations"]["detail"]


@pytest.mark.django_db
class TestSanityChecksView:
    def test_anonymous_is_rejected(self, api_client):
        response = api_client.get(URL)
        assert response.status_code == 401

    def test_regular_user_is_forbidden(self, authenticated_client):
        response = authenticated_client.get(URL)
        assert response.status_code == 403

    def test_superuser_gets_report(self, management_client):
        canned = {"migrations": {"ok": True, "has_pending": False, "pending": [], "detail": None}}
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

    def test_live_response_matches_the_published_schema(self, management_client):
        """Nothing patched: the real report must carry exactly the fields
        apps/common/schema.yaml declares, so the two can't drift apart."""
        response = management_client.get(URL)
        assert response.status_code == 200
        _assert_shape(_schema_shape(), response.data)


class TestSendTestEmail:
    @override_settings(
        ADMINS=["someone@example.com", "other@example.com"],
        SERVER_EMAIL="server@example.com",
        DEFAULT_FROM_EMAIL="default-from@example.com",
        EMAIL_SUBJECT_PREFIX="[Archetype] ",
    )
    def test_sends_as_the_error_notification_path_does(self, mailoutbox):
        # The point of the test email is to prove `mail_admins` would arrive, so
        # it must use SERVER_EMAIL and the subject prefix — not DEFAULT_FROM_EMAIL.
        result = sc.send_test_email()

        assert result == {"sent": True, "detail": "Test email sent to someone@example.com, other@example.com."}
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["someone@example.com", "other@example.com"]
        assert mailoutbox[0].from_email == "server@example.com"
        assert mailoutbox[0].subject.startswith("[Archetype] ")

    @override_settings(ADMINS=["someone@example.com"])
    def test_smtp_exception_is_reported_without_raising(self):
        # `except OSError` has to keep covering smtplib's hierarchy.
        with patch("apps.common.services.sanity_checks.mail_admins", side_effect=SMTPException("bad hello")):
            result = sc.send_test_email()
        assert result["sent"] is False
        assert "bad hello" in result["detail"]

    @override_settings(ADMINS=["someone@example.com"])
    def test_unrelated_exceptions_propagate(self):
        # Only OSError delivery failures are swallowed here — a bug
        # elsewhere (e.g. a bad argument) should raise, not be reported as an
        # "SMTP problem".
        with patch("apps.common.services.sanity_checks.mail_admins", side_effect=ValueError("not smtp related")):
            with pytest.raises(ValueError):
                sc.send_test_email()


@pytest.mark.django_db
class TestSanityCheckTestEmailView:
    def test_anonymous_is_rejected(self, api_client):
        response = api_client.post(TEST_EMAIL_URL)
        assert response.status_code in (401, 403)

    def test_regular_user_is_forbidden(self, authenticated_client):
        response = authenticated_client.post(TEST_EMAIL_URL)
        assert response.status_code == 403

    def test_smtp_not_configured_short_circuits_without_sending(self, management_client):
        with (
            patch("apps.common.views.smtp_configured", return_value=False),
            patch("apps.common.views.send_test_email") as send_mock,
        ):
            response = management_client.post(TEST_EMAIL_URL)
        assert response.status_code == 400
        assert response.data["sent"] is False
        send_mock.assert_not_called()

    def test_published_schema_does_not_require_a_request_body(self):
        # post() never reads request.data. A required body would hand every
        # generated client a mandatory argument the endpoint silently discards.
        schema = yaml.safe_load((settings.BASE_DIR / "apps/common/schema.yaml").read_text(encoding="utf-8"))
        assert "requestBody" not in schema["paths"][TEST_EMAIL_URL]["post"]

    @override_settings(ADMINS=[])
    def test_no_recipients_is_400_not_a_relay_failure(self, management_client, mailoutbox):
        with patch("apps.common.views.smtp_configured", return_value=True):
            response = management_client.post(TEST_EMAIL_URL)
        assert response.status_code == 400
        assert response.data["sent"] is False
        assert mailoutbox == []

    @override_settings(ADMINS=["someone@example.com"])
    def test_successful_send_returns_200_with_expected_args(self, management_client):
        with (
            patch("apps.common.views.smtp_configured", return_value=True),
            patch("apps.common.views.send_test_email") as send_mock,
        ):
            send_mock.return_value = {"sent": True, "detail": "Test email sent to someone@example.com."}
            response = management_client.post(TEST_EMAIL_URL)
        assert response.status_code == 200
        assert response.data["sent"] is True
        send_mock.assert_called_once_with()

    @override_settings(ADMINS=["someone@example.com"])
    def test_send_failure_returns_error_response_without_500(self, management_client):
        with (
            patch("apps.common.views.smtp_configured", return_value=True),
            patch("apps.common.views.send_test_email") as send_mock,
        ):
            send_mock.return_value = {"sent": False, "detail": "Connection refused"}
            response = management_client.post(TEST_EMAIL_URL)
        assert response.status_code == 502
        assert response.data == {"sent": False, "detail": "Connection refused"}


def _schema_shape() -> dict:
    """Property-name tree of the SanityChecks component, local $refs resolved."""
    schemas = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))["components"]["schemas"]

    def shape(node: dict) -> dict | None:
        if "$ref" in node:
            node = schemas[node["$ref"].rsplit("/", 1)[-1]]
        if node.get("type") != "object":
            return None
        return {name: shape(sub) for name, sub in node["properties"].items()}

    return shape(schemas["SanityChecks"]) or {}


def _assert_shape(expected: dict, actual: dict, path: str = "") -> None:
    assert set(expected) == set(actual), (
        f"{path or 'response'}: schema declares {sorted(expected)}, response has {sorted(actual)}"
    )
    for key, sub in expected.items():
        if sub is not None:
            _assert_shape(sub, actual[key], f"{path}{key}.")
