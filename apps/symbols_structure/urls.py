from django.urls import path

from .views import AllographListView, PositionListView

urlpatterns = [
    path("allographs/", AllographListView.as_view(), name="allograph-list"),
    path("positions/", PositionListView.as_view(), name="allograph-list"),
]
