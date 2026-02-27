from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    BibliographicSourceManagementViewSet,
    CatalogueNumberManagementViewSet,
    CurrentItemManagementViewSet,
    HistoricalItemDescriptionManagementViewSet,
    HistoricalItemManagementViewSet,
    ImageTextManagementViewSet,
    ImageViewSet,
    ItemFormatManagementViewSet,
    ItemImageManagementViewSet,
    ItemPartManagementViewSet,
    ItemPartViewSet,
    RepositoryManagementViewSet,
    image_picker_content,
)

router = DefaultRouter()
router.register("item-parts", ItemPartViewSet)
router.register("item-images", ImageViewSet)
router.register("management/historical-items", HistoricalItemManagementViewSet, basename="management-historical-items")
router.register("management/item-parts", ItemPartManagementViewSet, basename="management-item-parts")
router.register("management/item-images", ItemImageManagementViewSet, basename="management-item-images")
router.register("management/image-texts", ImageTextManagementViewSet, basename="management-image-texts")
router.register(
    "management/catalogue-numbers",
    CatalogueNumberManagementViewSet,
    basename="management-catalogue-numbers",
)
router.register(
    "management/descriptions",
    HistoricalItemDescriptionManagementViewSet,
    basename="management-descriptions",
)
router.register("management/repositories", RepositoryManagementViewSet, basename="management-repositories")
router.register("management/current-items", CurrentItemManagementViewSet, basename="management-current-items")
router.register("management/sources", BibliographicSourceManagementViewSet, basename="management-sources")
router.register("management/formats", ItemFormatManagementViewSet, basename="management-formats")
urlpatterns = router.urls + [
    path("management/image-picker-content/", image_picker_content, name="management-image-picker-content"),
]
