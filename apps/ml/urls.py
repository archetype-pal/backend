from rest_framework import routers

from .views import MLJobManagementViewSet

router = routers.SimpleRouter()

router.register("management/ml-jobs", MLJobManagementViewSet, basename="management-ml-jobs")
urlpatterns = router.urls
