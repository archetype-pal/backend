"""URL config for the chunked image-upload API."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.uploads.views import UploadSessionViewSet, download_original

router = SimpleRouter()
router.register("sessions", UploadSessionViewSet, basename="upload-sessions")

urlpatterns = [
    path("item-images/<int:item_image_id>/original/", download_original, name="upload-download-original"),
    *router.urls,
]
