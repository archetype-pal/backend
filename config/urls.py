from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from apps.common.views import APISchemaView, SwaggerUIView

urlpatterns = (
    [
        path("tinymce/", include("tinymce.urls")),
        # Public read API
        path("api/v1/", include("apps.common.urls")),
        path("api/v1/search/", include("apps.search.urls")),
        path("api/v1/auth/", include("apps.users.urls")),
        path("api/v1/manuscripts/", include("apps.manuscripts.urls")),
        path("api/v1/", include("apps.scribes.urls")),
        path("api/v1/", include("apps.annotations.urls")),
        path("api/v1/symbols_structure/", include("apps.symbols_structure.urls")),
        path("api/v1/schema/", APISchemaView.as_view(), name="doc-schema"),
        path("api/v1/docs/", SwaggerUIView.as_view(), name="doc-ui"),
        path("api/v1/media/", include("apps.publications.urls")),
    ]
    + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
)
