from django.urls import path

from .views import SimilarHandsView

urlpatterns = [
    path("hands/<int:pk>/similar/", SimilarHandsView.as_view(), name="hand-similar"),
]
