from rest_framework import routers

from .views import (
    CarouselItemManagementViewSet,
    CarouselItemViewSet,
    CommentManagementViewSet,
    EventManagementViewSet,
    EventViewSet,
    PublicationManagementViewSet,
    PublicationViewSet,
)

router = routers.DefaultRouter()

router.register("events", EventViewSet, basename="events")
router.register("publications", PublicationViewSet, basename="publications")
router.register("carousel-items", CarouselItemViewSet, basename="carousel-items")
router.register("management/publications", PublicationManagementViewSet, basename="management-publications")
router.register("management/events", EventManagementViewSet, basename="management-events")
router.register("management/comments", CommentManagementViewSet, basename="management-comments")
router.register("management/carousel-items", CarouselItemManagementViewSet, basename="management-carousel-items")
urlpatterns = router.urls
