from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.views.generic import TemplateView
from django_filters import rest_framework as filters
from rest_framework import serializers, status, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
import yaml

from apps.common.audit import audit_actor
from apps.common.models import Date, SiteLabel
from apps.common.permissions import IsSuperuser, IsSuperuserOrReadOnly
from apps.common.services.sanity_checks import run_sanity_checks, send_test_email, smtp_configured

from .serializers import DateManagementSerializer


class AuditActorMixin:
    """Bind the request user as the audit actor around DRF write operations.

    The `EditEvent` post_save/post_delete signals fire *inside* `save()`/
    `delete()`, before a view could attach `_audit_actor` to the returned
    instance, so we set the actor via a contextvar for the duration of the
    write. Without this every audit row records `actor=None`.
    """

    def perform_create(self, serializer):
        with audit_actor(getattr(self.request, "user", None)):
            super().perform_create(serializer)

    def perform_update(self, serializer):
        with audit_actor(getattr(self.request, "user", None)):
            super().perform_update(serializer)

    def perform_destroy(self, instance):
        with audit_actor(getattr(self.request, "user", None)):
            super().perform_destroy(instance)


class BasePrivilegedViewSet(AuditActorMixin, viewsets.ModelViewSet):
    """All privileged ViewSets require superuser permissions."""

    permission_classes = [IsSuperuser]


class ActionSerializerMixin:
    """Map DRF actions to serializers to avoid repetitive conditionals."""

    action_serializer_classes: dict[str, type[serializers.Serializer]] = {}

    def get_serializer_class(self) -> type[serializers.Serializer]:  # noqa: D401 - DRF framework method
        serializer_class = self.action_serializer_classes.get(getattr(self, "action", ""))
        if serializer_class is not None:
            return serializer_class
        return super().get_serializer_class()  # type: ignore[misc, no-any-return]


class FilterablePrivilegedViewSet(BasePrivilegedViewSet):
    """Privileged ViewSet with DjangoFilterBackend and SearchFilter pre-configured."""

    filter_backends = [filters.DjangoFilterBackend, SearchFilter]


class UnpaginatedPrivilegedViewSet(BasePrivilegedViewSet):
    """Privileged ViewSet for small lookup tables (no pagination)."""

    pagination_class = None


class APISchemaView(APIView):
    @staticmethod
    def _load_schema_file(schema_path: Path | str) -> dict[str, Any]:
        with open(schema_path, encoding="utf-8") as file:
            schema_object: Any = yaml.safe_load(file.read()) or {}

        if not isinstance(schema_object, dict):
            raise ValueError(f"Invalid schema format in {schema_path}. Expected a mapping object.")
        schema_object.setdefault("paths", {})
        schema_object.setdefault("components", {})
        schema_object.setdefault("tags", [])
        return schema_object

    def get(self, request: Request) -> Response:
        core_file: Path = settings.BASE_DIR / "apps/common/schema.yaml"
        supporting_files: list[Path] = [
            settings.BASE_DIR / "apps/users/schema.yaml",
            settings.BASE_DIR / "apps/publications/schema.yaml",
            settings.BASE_DIR / "apps/symbols_structure/schema.yaml",
            settings.BASE_DIR / "apps/manuscripts/schema.yaml",
            settings.BASE_DIR / "apps/scribes/schema.yaml",
            settings.BASE_DIR / "apps/annotations/schema.yaml",
            settings.BASE_DIR / "apps/worksets/schema.yaml",
            settings.BASE_DIR / "apps/pages/schema.yaml",
        ]
        core_object: dict[str, Any] = self._load_schema_file(core_file)
        for supporting_file in supporting_files:
            documentation_object: dict[str, Any] = self._load_schema_file(supporting_file)
            core_object["paths"].update(documentation_object.get("paths", {}))
            if "schemas" in documentation_object.get("components", {}):
                core_object["components"].setdefault("schemas", {})
                core_object["components"]["schemas"].update(documentation_object["components"]["schemas"])
            core_object["tags"] += documentation_object.get("tags", [])
        return Response(data=core_object)


class SwaggerUIView(TemplateView):
    template_name = "swagger-ui.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data()
        # Only honour a same-origin, root-relative schema path. An arbitrary
        # attacker-supplied ?openapi_url= would otherwise point Swagger UI at a
        # foreign spec (and issue cross-origin requests on the user's behalf).
        requested = self.request.GET.get("openapi_url", "")
        openapi_url = requested if requested.startswith("/") and not requested.startswith("//") else "/api/v1/schema/"
        context.update({"openapi_schema_url": openapi_url})
        return context


class SanityChecksView(APIView):
    """Superuser-only operational health snapshot.

    Reports pending migrations, dependent-service reachability (database,
    redis, meilisearch, celery broker), whether SMTP looks configured,
    database size, media directory size, and filesystem writability — see
    `apps.common.services.sanity_checks` for the actual check logic.
    """

    permission_classes = [IsSuperuser]

    def get(self, request: Request) -> Response:
        return Response(run_sanity_checks())


class SanityCheckTestEmailView(APIView):
    """Superuser-only: send a real test email to ADMIN_EMAILS to verify SMTP delivery end-to-end.

    Both "nothing to try" cases — SMTP unconfigured, no recipients — short-circuit
    with 400, so a 502 means only that a configured relay refused the message.
    """

    permission_classes = [IsSuperuser]

    def post(self, request: Request) -> Response:
        if not smtp_configured():
            return Response(
                {"sent": False, "detail": "SMTP is not configured (EMAIL_HOST is unset or still the default)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not settings.ADMINS:
            return Response(
                {"sent": False, "detail": "No ADMIN_EMAILS configured to send a test email to."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = send_test_email()
        response_status = status.HTTP_200_OK if result["sent"] else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=response_status)


class DateManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Date.objects.all()
    serializer_class = DateManagementSerializer


class SiteLabelsView(APIView):
    """Per-key store for customizable UI label translations.

    GET is public (every page render needs labels, including anonymous
    visitors) and assembles the full `{key: {en, fr}}` dict from all
    `SiteLabel` rows; PUT is superuser-only and upserts only the keys present
    in the payload — unlike the old singleton's full-blob overwrite, keys
    absent from the payload are left untouched.
    """

    permission_classes = [IsSuperuserOrReadOnly]

    def get(self, request: Request) -> Response:
        rows = {row.key: row.value for row in SiteLabel.objects.all()}
        return Response({"labels": rows})

    def put(self, request: Request) -> Response:
        payload = request.data.get("labels")
        if not isinstance(payload, dict):
            raise serializers.ValidationError({"labels": "This field is required and must be an object."})

        unknown = set(payload) - set(SiteLabel.Key.values)
        if unknown:
            raise serializers.ValidationError({"labels": f"Unknown key(s): {sorted(unknown)}"})

        invalid_keys = [
            key
            for key, value in payload.items()
            if not isinstance(value, dict) or not value or not all(isinstance(text, str) for text in value.values())
        ]
        if invalid_keys:
            raise serializers.ValidationError(
                {
                    "labels": (
                        f"Value(s) for key(s) {sorted(invalid_keys)} must be a non-empty object "
                        "of {lang: text} strings."
                    )
                }
            )

        with transaction.atomic(), audit_actor(getattr(request, "user", None)):
            for key, value in payload.items():
                SiteLabel.objects.update_or_create(key=key, defaults={"value": value})

        rows = {row.key: row.value for row in SiteLabel.objects.all()}
        return Response({"labels": rows})
