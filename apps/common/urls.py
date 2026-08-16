from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DateManagementViewSet, SanityChecksView, SanityCheckTestEmailView, SiteLabelsView

router = DefaultRouter()
router.register("management/common/dates", DateManagementViewSet, basename="management-dates")

urlpatterns = router.urls + [
    path("site-labels/", SiteLabelsView.as_view(), name="site-labels"),
    path("management/common/sanity-checks/", SanityChecksView.as_view(), name="management-sanity-checks"),
    path(
        "management/common/sanity-checks/test-email/",
        SanityCheckTestEmailView.as_view(),
        name="management-sanity-checks-test-email",
    ),
]
