from rest_framework.routers import DefaultRouter

from .views import ImageViewSet, ItemPartViewSet

router = DefaultRouter()
router.register("item-parts", ItemPartViewSet)
router.register("item-images", ImageViewSet)
urlpatterns = router.urls
