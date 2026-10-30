from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
import yaml

from apps.common.audit import audit_actor
from apps.common.models import Date, Place, SiteLabel
from apps.common.permissions import IsSuperuser, IsSuperuserOrReadOnly
from apps.common.services.sanity_checks import run_sanity_checks, send_test_email, smtp_configured
from apps.common.services.site_features import get_site_features, replace_site_features
from apps.common.viewsets import UnpaginatedPrivilegedViewSet

from .serializers import (
    BrandingLogoUploadSerializer,
    DateManagementSerializer,
    PlaceManagementSerializer,
    SiteFeaturesWriteSerializer,
    SiteLabelsWriteSerializer,
    validated_data,
)


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
        # `common/schema.yaml` carries the document header; every other app's file contributes paths.
        core_file: Path = settings.BASE_DIR / "apps/common/schema.yaml"
        core_object: dict[str, Any] = self._load_schema_file(core_file)
        for supporting_file in sorted(settings.BASE_DIR.glob("apps/*/schema.yaml")):
            if supporting_file == core_file:
                continue
            documentation_object: dict[str, Any] = self._load_schema_file(supporting_file)
            core_object["paths"].update(documentation_object.get("paths", {}))
            for section, entries in documentation_object.get("components", {}).items():
                core_object["components"].setdefault(section, {}).update(entries)
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
    redis, meilisearch, celery broker and worker liveness), whether SMTP looks
    configured, database and media sizes, and filesystem writability — see
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
                {"sent": False, "detail": "SMTP is not configured (EMAIL_HOST or EMAIL_BACKEND is still the default)."},
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


class PlaceManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Place.objects.all()
    serializer_class = PlaceManagementSerializer


class SiteLabelsView(APIView):
    """Per-key store for customizable UI label translations.

    GET is public (every page render needs labels, including anonymous
    visitors) and assembles the full `{key: {en, fr}}` dict from all
    `SiteLabel` rows; PUT is superuser-only and upserts only the keys present
    in the payload — unlike the old singleton's full-blob overwrite, keys
    absent from the payload are left untouched.
    """

    permission_classes = [IsSuperuserOrReadOnly]

    @staticmethod
    def _all_labels() -> Response:
        return Response({"labels": {row.key: row.value for row in SiteLabel.objects.all()}})

    def get(self, request: Request) -> Response:
        return self._all_labels()

    def put(self, request: Request) -> Response:
        labels = validated_data(SiteLabelsWriteSerializer, request.data)["labels"]
        with transaction.atomic(), audit_actor(request.user):
            for key, value in labels.items():
                SiteLabel.objects.update_or_create(key=key, defaults={"value": value})
        return self._all_labels()


class SiteFeaturesView(APIView):
    """Per-key store for the public site-features configuration (see `services.site_features`)."""

    permission_classes = [IsSuperuserOrReadOnly]

    def get(self, request: Request) -> Response:
        return Response(get_site_features())

    def put(self, request: Request) -> Response:
        """Full replace: every stored key absent from the payload is deleted."""
        features = validated_data(SiteFeaturesWriteSerializer, request.data)
        return Response(replace_site_features(features, actor=request.user))


class BrandingLogoUploadView(APIView):
    """Accept an uploaded logo image and return its stored URL.

    `Partner.logo` is an `ImageField` on a model row, so Django saves the
    file as a side effect of that row's own save(). `branding.logoUrl` has no
    row to attach a `FileField` to — it's one leaf among the `AppSettings`
    rows `SiteFeaturesView` reads/writes — so the file goes straight through
    `default_storage` here, and the frontend PUTs the returned URL into
    `branding.logoUrl` as a separate step via `SiteFeaturesView`.
    """

    permission_classes = [IsSuperuser]
    parser_classes = [MultiPartParser]

    def post(self, request: Request) -> Response:
        logo = validated_data(BrandingLogoUploadSerializer, request.data)["logo"]
        path = default_storage.save(f"branding/{logo.name}", logo)
        return Response({"url": default_storage.url(path)}, status=status.HTTP_201_CREATED)


class VersionView(APIView):
    """Report which build is running, for anyone checking what is deployed.

    Both values are baked into the image by CD and read back from settings, so
    they describe the *build*, not the working tree: a container started from a
    published image reports that image's release, and one started from a source
    checkout reports `dev`/`unknown`. Deliberately public and unauthenticated —
    knowing the release of a running deployment is the whole point, and it
    exposes nothing a caller could not learn from the repository.
    """

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"version": settings.APP_VERSION, "commit": settings.APP_COMMIT})
