from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DateManagementViewSet,
    PlaceManagementViewSet,
    SanityChecksView,
    SanityCheckTestEmailView,
    SiteFeaturesView,
    SiteLabelsView,
)

router = DefaultRouter()
router.register("management/common/dates", DateManagementViewSet, basename="management-dates")
router.register("management/common/places", PlaceManagementViewSet, basename="management-places")

urlpatterns = router.urls + [
    path("site-labels/", SiteLabelsView.as_view(), name="site-labels"),
    path("app-settings/", SiteFeaturesView.as_view(), name="app-settings"),
    path("management/common/sanity-checks/", SanityChecksView.as_view(), name="management-sanity-checks"),
    path(
        "management/common/sanity-checks/test-email/",
        SanityCheckTestEmailView.as_view(),
        name="management-sanity-checks-test-email",
    ),
]
