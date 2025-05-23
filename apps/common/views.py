from django.conf import settings
from django.views.generic import TemplateView
from rest_framework.response import Response
from rest_framework.views import APIView
import yaml


class APISchemaView(APIView):
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
        with open(core_file, encoding="utf-8") as file:
            core_object = yaml.load(file.read(), Loader=yaml.Loader)
        for supporting_file in supporting_files:
            with open(supporting_file, encoding="utf-8") as file:
                documentation_object = yaml.load(file.read(), Loader=yaml.Loader)
                core_object["paths"].update(documentation_object["paths"])
                if "components" in documentation_object and "schemas" in core_object["components"]:
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
