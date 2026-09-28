from django.urls import path

from . import views

urlpatterns = [
    path("graphs/<int:graph_id>/", views.graph_annotation, name="w3c-graph-annotation"),
    path("image-texts/<int:text_id>/", views.image_text_page, name="w3c-image-text-page"),
    path("context/", views.context, name="w3c-context"),
]
