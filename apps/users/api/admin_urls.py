from rest_framework.routers import DefaultRouter

from .admin_views import UserAdminViewSet

router = DefaultRouter()
router.register("users", UserAdminViewSet, basename="admin-users")

urlpatterns = router.urls
