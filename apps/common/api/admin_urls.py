from rest_framework.routers import DefaultRouter

from .admin_views import DateAdminViewSet

router = DefaultRouter()
router.register("common/dates", DateAdminViewSet, basename="admin-dates")

urlpatterns = router.urls
