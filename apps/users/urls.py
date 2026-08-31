from django.urls import path
from djoser import views
from rest_framework.routers import DefaultRouter

from .views import LoginThrottle, TokenLogoutView, UserManagementViewSet, UserProfileView

router = DefaultRouter()
router.register("management/users", UserManagementViewSet, basename="management-users")

urlpatterns = router.urls + [
    path("token/login", views.TokenCreateView.as_view(throttle_classes=[LoginThrottle]), name="login"),
    path("token/logout", TokenLogoutView.as_view(), name="logout"),
    path("profile", UserProfileView.as_view(), name="profile"),
]
