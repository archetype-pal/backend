from django.urls import path

from . import views

urlpatterns = [
    path("item-parts/<int:item_part_id>/manifest", views.item_part_manifest, name="iiif-manifest"),
]
