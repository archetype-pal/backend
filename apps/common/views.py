from django.conf import settings
from django.views.generic import TemplateView
from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
import yaml

from apps.common.models import Date
from apps.common.permissions import IsSuperuser

from .serializers import DateManagementSerializer


class BasePrivilegedViewSet(viewsets.ModelViewSet):
    """All privileged ViewSets require superuser permissions."""

    permission_classes = [IsSuperuser]


class FilterablePrivilegedViewSet(BasePrivilegedViewSet):
    """Privileged ViewSet with DjangoFilterBackend pre-configured."""

    filter_backends = [filters.DjangoFilterBackend]


class UnpaginatedPrivilegedViewSet(BasePrivilegedViewSet):
    """Privileged ViewSet for small lookup tables (no pagination)."""

    pagination_class = None


class APISchemaView(APIView):
    @staticmethod
    def _load_schema_file(schema_path):
        with open(schema_path, encoding="utf-8") as file:
            schema_object = yaml.safe_load(file.read()) or {}

        if not isinstance(schema_object, dict):
            raise ValueError(f"Invalid schema format in {schema_path}. Expected a mapping object.")
        schema_object.setdefault("paths", {})
        schema_object.setdefault("components", {})
        schema_object.setdefault("tags", [])
        return schema_object

    def get(self, request):
        core_file = settings.BASE_DIR / "apps/common/schema.yaml"
        supporting_files = [
            settings.BASE_DIR / "apps/users/schema.yaml",
            settings.BASE_DIR / "apps/publications/schema.yaml",
            settings.BASE_DIR / "apps/symbols_structure/schema.yaml",
            settings.BASE_DIR / "apps/manuscripts/schema.yaml",
            settings.BASE_DIR / "apps/scribes/schema.yaml",
            settings.BASE_DIR / "apps/annotations/schema.yaml",
        ]
        core_object = self._load_schema_file(core_file)
        for supporting_file in supporting_files:
            documentation_object = self._load_schema_file(supporting_file)
            core_object["paths"].update(documentation_object.get("paths", {}))
            if "schemas" in documentation_object.get("components", {}):
                core_object["components"].setdefault("schemas", {})
                core_object["components"]["schemas"].update(documentation_object["components"]["schemas"])
            core_object["tags"] += documentation_object.get("tags", [])
        return Response(data=core_object)


class SwaggerUIView(TemplateView):
    template_name = "swagger-ui.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context.update(
            {
                "openapi_schema_url": self.request.GET.get("openapi_url", "/api/v1/schema/"),
            }
        )
        return context


class DateManagementViewSet(UnpaginatedPrivilegedViewSet):
    queryset = Date.objects.all()
    serializer_class = DateManagementSerializer
