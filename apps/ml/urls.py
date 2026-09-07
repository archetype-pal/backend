from rest_framework import routers

from .views import MLJobManagementViewSet

router = routers.DefaultRouter()

router.register("management/ml-jobs", MLJobManagementViewSet, basename="management-ml-jobs")
urlpatterns = router.urls
