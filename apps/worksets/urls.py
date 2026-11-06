from rest_framework import routers

from .views import WorksetViewSet

router = routers.SimpleRouter()
router.register("worksets", WorksetViewSet, basename="worksets")
urlpatterns = router.urls
