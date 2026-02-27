from rest_framework.routers import DefaultRouter

from .views import DateManagementViewSet

router = DefaultRouter()
router.register("management/common/dates", DateManagementViewSet, basename="management-dates")

urlpatterns = router.urls
