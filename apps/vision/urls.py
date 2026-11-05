from django.urls import path

from .views import FindOnPageView, PageDraftListView, PageDraftView, ScribeSimilarHandsView, SimilarHandsView

urlpatterns = [
    path("hands/<int:pk>/similar/", SimilarHandsView.as_view(), name="hand-similar"),
    path("scribes/<int:pk>/similar/", ScribeSimilarHandsView.as_view(), name="scribe-similar"),
    path("management/vision/pages/<int:pk>/find/", FindOnPageView.as_view(), name="page-find"),
    path("management/vision/pages/<int:pk>/draft/", PageDraftView.as_view(), name="page-draft"),
    path("management/vision/drafts/", PageDraftListView.as_view(), name="page-drafts"),
]
