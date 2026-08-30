import json
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
from apps.common.models import AppSettings, Date, SiteLabel
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


class TrashableViewSetMixin:
    """Turn DRF's destroy into a soft delete for SoftDeleteModel rows.

    List before AuditActorMixin/ModelViewSet so this perform_destroy wins.
    Being a save(), it does not fire pre_delete/post_delete — only a purge does.
    """

    def perform_destroy(self, instance):
        with audit_actor(getattr(self.request, "user", None)):
            instance.soft_delete(user=getattr(self.request, "user", None))


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


SITE_FEATURES_KEY = "site_features"
SITE_FEATURES_KEY_PREFIX = f"{SITE_FEATURES_KEY}."


def flatten_settings(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested dict into {dotted.path: leaf_value}.

    Lists (and other non-dict values) are leaves, not further split: a row
    per *setting*, not a row per list item — `sectionOrder` or
    `visibleColumns` are each one setting whose value happens to be a list.
    """
    flat: dict[str, Any] = {}
    for sub_key, sub_value in obj.items():
        dotted_key = f"{prefix}.{sub_key}" if prefix else sub_key
        if isinstance(sub_value, dict):
            flat.update(flatten_settings(sub_value, dotted_key))
        else:
            flat[dotted_key] = sub_value
    return flat


def unflatten_settings(flat: dict[str, Any]) -> dict[str, Any]:
    """Inverse of `flatten_settings`: rebuild a nested dict from dotted keys.

    A row whose key collides with another row's prefix (e.g. both `sections`
    and `sections.search`) is malformed — created by a bug or by hand, since
    `flatten_settings` never produces that pairing itself. Skip it rather than
    crash, consistent with this view never 500ing on corrupt settings data.
    """
    nested: dict[str, Any] = {}
    # Deepest keys first: a proper prefix always has fewer dots, so it is
    # consumed after the subtree it collides with and the leaf guard drops it.
    for dotted_key, value in sorted(flat.items(), key=lambda kv: kv[0].count("."), reverse=True):
        *parents, leaf = dotted_key.split(".")
        node = nested
        for part in parents:
            node = node.setdefault(part, {})
        if not isinstance(node.get(leaf), dict):
            node[leaf] = value
    return nested


# Mirrors config/site-features.json in the frontend repo. Kept in sync
# manually with that file and with the seed data in
# 0010_seed_site_features.py — there are three of these because the frontend
# needs its own same-process default, the migration needs a self-contained
# one-time seed value, and this one is the last-resort fallback so `GET` never
# 500s even if every `AppSettings` row for this key is missing, deactivated,
# or corrupt.
DEFAULT_SITE_FEATURES: dict[str, Any] = {
    "sections": {
        "search": True,
        "collection": True,
        "lightbox": True,
        "news": True,
        "blogs": True,
        "featureArticles": True,
        "events": True,
        "about": True,
    },
    "sectionOrder": [
        "search",
        "lightbox",
        "collection",
        "blogs",
        "featureArticles",
        "about",
        "news",
        "events",
    ],
    "features": {"manuscriptDescriptions": True},
    "searchCategories": {
        "manuscripts": {
            "enabled": True,
            "visibleColumns": [
                "Repository City",
                "Repository",
                "Shelfmark",
                "Catalogue Num.",
                "Text Date",
                "Doc. Type",
                "Images",
            ],
            "visibleFacets": [
                "image_availability",
                "text_date",
                "format",
                "type",
                "repository_city",
                "repository_name",
                "script",
                "material",
                "deco_type",
                "seal_type",
                "seal_material",
                "origin_place",
            ],
        },
        "images": {
            "enabled": True,
            "visibleColumns": [
                "Repository City",
                "Repository",
                "Shelfmark",
                "Doc. Type",
                "Thumbnail",
                "Annotations",
            ],
            "visibleFacets": [
                "text_date",
                "locus",
                "type",
                "repository_city",
                "repository_name",
                "features",
                "components",
                "component_features",
                "tags",
            ],
        },
        "scribes": {
            "enabled": True,
            "visibleColumns": ["Scribe Name", "Date", "Scriptorium"],
            "visibleFacets": ["text_date", "scriptorium"],
        },
        "hands": {
            "enabled": True,
            "visibleColumns": [
                "Hand Title",
                "Repository City",
                "Repository",
                "Shelfmark",
                "Place",
                "Date",
                "Catalogue Num.",
            ],
            "visibleFacets": ["text_date", "repository_name", "repository_city", "place"],
        },
        "graphs": {
            "enabled": True,
            "visibleColumns": [
                "Repository City",
                "Repository",
                "Shelfmark",
                "Document Date",
                "Allograph",
                "Character",
                "Hand Name",
                "Thumbnail",
            ],
            "visibleFacets": [
                "character",
                "character_type",
                "allograph",
                "place",
                "repository_name",
                "repository_city",
                "features",
                "components",
                "component_features",
                "positions",
            ],
        },
        "texts": {
            "enabled": True,
            "visibleColumns": ["Repository City", "Repository", "Shelfmark", "Text Type", "MS Date"],
            "visibleFacets": [
                "text_date",
                "text_type",
                "type",
                "repository_city",
                "repository_name",
                "status",
                "language",
                "places",
                "people",
            ],
        },
        "clauses": {
            "enabled": True,
            "visibleColumns": [
                "Cat. Num.",
                "Document Type",
                "Repository City",
                "Repository",
                "Shelfmark",
                "Text Date",
                "Text Type",
                "Clause Type",
            ],
            "visibleFacets": [
                "type",
                "repository_city",
                "repository_name",
                "text_date",
                "text_type",
                "clause_type",
                "status",
            ],
        },
        "people": {
            "enabled": True,
            "visibleColumns": [
                "Cat. Num.",
                "Document Type",
                "Repository City",
                "Repository",
                "Shelfmark",
                "Text Date",
                "Text Type",
                "Category",
            ],
            "visibleFacets": [
                "type",
                "repository_city",
                "repository_name",
                "text_date",
                "text_type",
                "person_type",
                "status",
            ],
        },
        "places": {
            "enabled": True,
            "visibleColumns": [
                "Cat. Num.",
                "Document Type",
                "Repository City",
                "Repository",
                "Shelfmark",
                "Text Date",
                "Text Type",
                "Place Type",
            ],
            "visibleFacets": [
                "type",
                "repository_city",
                "repository_name",
                "text_date",
                "text_type",
                "place_type",
                "status",
            ],
        },
    },
}


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data: Any) -> Any:
        # PUT is a destructive full replace, so an unknown key would be dropped
        # by DRF and then have its stored rows deleted behind a 200.
        if isinstance(data, dict) and (unknown := set(data) - set(self.fields)):
            raise serializers.ValidationError({key: "Unknown key." for key in unknown})
        return super().to_internal_value(data)


class SearchCategoryWriteSerializer(StrictSerializer):
    enabled = serializers.BooleanField()
    visibleColumns = serializers.ListField(child=serializers.CharField())
    visibleFacets = serializers.ListField(child=serializers.CharField())


class SiteFeaturesWriteSerializer(StrictSerializer):
    sections = serializers.DictField(child=serializers.BooleanField(), allow_empty=False)
    sectionOrder = serializers.ListField(child=serializers.CharField())
    features = serializers.DictField(child=serializers.BooleanField(), allow_empty=False)
    searchCategories = serializers.DictField(child=SearchCategoryWriteSerializer(), allow_empty=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        limit = AppSettings._meta.get_field("key").max_length - len(SITE_FEATURES_KEY_PREFIX)
        if any(len(dotted_key) > limit for dotted_key in flatten_settings(attrs)):
            raise serializers.ValidationError(f"Setting keys must be at most {limit} characters.")
        return attrs


class SiteFeaturesView(APIView):
    """Per-key store for the public site-features configuration.

    Replaces the old `config/site-features.json` file on the frontend
    """

    permission_classes = [IsSuperuserOrReadOnly]

    def get(self, request: Request) -> Response:
        # `is_public=True` is the enforced boundary (see AppSettings docstring)
        # — the key prefix narrows to *which* settings this view owns, `is_public`
        # is what makes them safe to serve to an anonymous caller. A row under
        # this prefix that isn't flagged public (e.g. created by a bug, or by
        # hand) is silently excluded rather than served.
        rows = AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX, is_active=True, is_public=True)
        flat: dict[str, Any] = {}
        for row in rows:
            try:
                flat[row.key[len(SITE_FEATURES_KEY_PREFIX) :]] = json.loads(row.value)
            except (TypeError, ValueError):  # fmt: skip
                continue
        if not flat:
            return Response(DEFAULT_SITE_FEATURES)
        return Response(unflatten_settings(flat))

    def put(self, request: Request) -> Response:
        """Full replace: every stored key absent from the payload is deleted."""
        serializer = SiteFeaturesWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        flat = flatten_settings(serializer.validated_data)
        keys = {f"{SITE_FEATURES_KEY_PREFIX}{dotted_key}" for dotted_key in flat}

        with transaction.atomic(), audit_actor(getattr(request, "user", None)):
            AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX).exclude(key__in=keys).delete()
            stored = dict(
                AppSettings.objects.filter(
                    key__startswith=SITE_FEATURES_KEY_PREFIX, is_active=True, is_public=True
                ).values_list("key", "value")
            )
            for dotted_key, value in flat.items():
                key = f"{SITE_FEATURES_KEY_PREFIX}{dotted_key}"
                encoded = json.dumps(value)
                if stored.get(key) == encoded:
                    continue  # every save emits an EditEvent; don't audit no-op writes
                AppSettings.objects.update_or_create(
                    key=key,
                    defaults={
                        "value": encoded,
                        "description": f"Site feature setting '{dotted_key}' (public site-features config).",
                        "is_active": True,
                        "is_public": True,
                    },
                )

        rows = AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX, is_active=True, is_public=True)
        result = {row.key[len(SITE_FEATURES_KEY_PREFIX) :]: json.loads(row.value) for row in rows}
        return Response(unflatten_settings(result))
