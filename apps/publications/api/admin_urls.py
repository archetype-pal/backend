from rest_framework.routers import DefaultRouter

from .admin_views import (
    CarouselItemAdminViewSet,
    CommentAdminViewSet,
    EventAdminViewSet,
    PublicationAdminViewSet,
)

router = DefaultRouter()
router.register("publications/publications", PublicationAdminViewSet, basename="admin-publications")
router.register("publications/events", EventAdminViewSet, basename="admin-events")
router.register("publications/comments", CommentAdminViewSet, basename="admin-comments")
router.register(
    "publications/carousel-items", CarouselItemAdminViewSet, basename="admin-carousel-items"
)

urlpatterns = router.urls
