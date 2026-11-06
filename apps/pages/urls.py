from rest_framework import routers

from .views import MenuHeadingManagementViewSet, MenuHeadingViewSet, PageManagementViewSet, PageViewSet

router = routers.SimpleRouter()

router.register("pages", PageViewSet, basename="pages")
router.register("management/pages", PageManagementViewSet, basename="management-pages")
router.register("menu-headings", MenuHeadingViewSet, basename="menu-headings")
router.register("management/menu-headings", MenuHeadingManagementViewSet, basename="management-menu-headings")
urlpatterns = router.urls
