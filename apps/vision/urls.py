from django.urls import path

from .views import ScribeSimilarHandsView, SimilarHandsView

urlpatterns = [
    path("hands/<int:pk>/similar/", SimilarHandsView.as_view(), name="hand-similar"),
    path("scribes/<int:pk>/similar/", ScribeSimilarHandsView.as_view(), name="scribe-similar"),
]
