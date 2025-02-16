from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import HandItemImagesForAdmin, HandViewSet, ScribeViewSet

router = DefaultRouter()
router.register("scribes", ScribeViewSet)
router.register("hands", HandViewSet)


urlpatterns = router.urls + [
    path("admin/get_item_images/", HandItemImagesForAdmin.as_view(), name="get_item_images"),
]
