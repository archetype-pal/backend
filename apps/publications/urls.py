from rest_framework import routers

from .views import CarouselItemViewSet, EventViewSet, PublicationViewSet

router = routers.DefaultRouter()

router.register("events", EventViewSet, basename="events")
router.register("publications", PublicationViewSet, basename="publications")
router.register("carousel-items", CarouselItemViewSet, basename="carousel-items")
urlpatterns = router.urls
