import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.views.generic import TemplateView
from django_filters import rest_framework as filters
from rest_framework import serializers, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
import yaml

from apps.common.audit import audit_actor
from apps.common.models import AppSettings, Date, SiteLabel
from apps.common.permissions import IsSuperuser, IsSuperuserOrReadOnly

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

# Mirrors config/site-features.json in the frontend repo. Kept in sync
# manually with that file and with the seed data in
# 0010_seed_site_features.py — there are three of these because the frontend
# needs its own same-process default, the migration needs a self-contained
# one-time seed value, and this one is the last-resort fallback so `GET` never
# 500s even if the `AppSettings` row is missing, deactivated, or corrupt.
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


class SiteFeaturesView(APIView):
    """Single-row store for the public site-features configuration blob.

    Replaces the old `config/site-features.json` file on the frontend: the
    entire blob (section visibility, section order, per-search-category
    column/facet visibility) is stored as one `AppSettings` row
    (`key="site_features"`), JSON-encoded, rather than modelled field-by-field
    — the nested shape is owned and validated by the frontend, this endpoint
    is just storage/transport for it.

    GET is public (every page render needs this config, including anonymous
    visitors) and returns the raw config object at the top level — no wrapper
    key, unlike `SiteLabelsView` — matching what used to be the raw JSON
    file's shape. PUT is superuser-only.
    """

    permission_classes = [IsSuperuserOrReadOnly]

    def get(self, request: Request) -> Response:
        row = AppSettings.objects.filter(key=SITE_FEATURES_KEY, is_active=True).first()
        if row is not None:
            try:
                return Response(json.loads(row.value))
            except TypeError, ValueError:
                pass
        return Response(DEFAULT_SITE_FEATURES)

    def put(self, request: Request) -> Response:
        payload = request.data
        if not isinstance(payload, dict) or "sections" not in payload or "searchCategories" not in payload:
            raise serializers.ValidationError(
                {"detail": "Body must be a JSON object containing at least 'sections' and 'searchCategories'."}
            )

        with transaction.atomic(), audit_actor(getattr(request, "user", None)):
            row, _ = AppSettings.objects.update_or_create(
                key=SITE_FEATURES_KEY,
                defaults={
                    "value": json.dumps(payload),
                    "description": (
                        "Public site-features configuration blob (section visibility, section "
                        "order, and per-search-category column/facet visibility) served to the "
                        "frontend in place of the old config/site-features.json file."
                    ),
                    "is_active": True,
                },
            )

        return Response(json.loads(row.value))
