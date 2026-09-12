"""URL config for the chunked image-upload API."""

from rest_framework.routers import SimpleRouter

from apps.uploads.views import ImageUploadSessionViewSet

router = SimpleRouter()
router.register("sessions", ImageUploadSessionViewSet, basename="upload-sessions")

urlpatterns = router.urls
