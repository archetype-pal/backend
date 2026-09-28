from django.urls import path

from . import views

urlpatterns = [
    path("item-parts/<int:item_part_id>/manifest", views.item_part_manifest, name="iiif-manifest"),
    path("item-parts/<int:item_part_id>/search", views.item_part_search, name="iiif-content-search"),
]
