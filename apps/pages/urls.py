from rest_framework import routers

from .views import PageManagementViewSet, PageViewSet

router = routers.DefaultRouter()

router.register("pages", PageViewSet, basename="pages")
router.register("management/pages", PageManagementViewSet, basename="management-pages")
urlpatterns = router.urls
