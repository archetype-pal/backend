from rest_framework.routers import DefaultRouter

from .views import DateManagementViewSet, EditEventListViewSet

router = DefaultRouter()
router.register("management/common/dates", DateManagementViewSet, basename="management-dates")
router.register("common/edit-events", EditEventListViewSet, basename="common-edit-events")

urlpatterns = router.urls
