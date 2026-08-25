"""URL config for the chunked image-upload API."""

from rest_framework.routers import SimpleRouter

from apps.uploads.views import UploadSessionViewSet

router = SimpleRouter()
router.register("sessions", UploadSessionViewSet, basename="upload-sessions")

urlpatterns = router.urls
