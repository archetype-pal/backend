from rest_framework import routers

from .views import (
    CarouselItemManagementViewSet,
    CarouselItemViewSet,
    CommentManagementViewSet,
    EventManagementViewSet,
    EventViewSet,
    PartnerManagementViewSet,
    PartnerViewSet,
    PublicationManagementViewSet,
    PublicationViewSet,
)

router = routers.DefaultRouter()

router.register("events", EventViewSet, basename="events")
router.register("publications", PublicationViewSet, basename="publications")
router.register("carousel-items", CarouselItemViewSet, basename="carousel-items")
router.register("partners", PartnerViewSet, basename="partners")
router.register("management/publications", PublicationManagementViewSet, basename="management-publications")
router.register("management/events", EventManagementViewSet, basename="management-events")
router.register("management/comments", CommentManagementViewSet, basename="management-comments")
router.register("management/carousel-items", CarouselItemManagementViewSet, basename="management-carousel-items")
router.register("management/partners", PartnerManagementViewSet, basename="management-partners")
urlpatterns = router.urls
