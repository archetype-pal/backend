"""Rules every Graph write path enforces: an annotation stays on its image and keeps its kind, and only superusers
touch editorial annotations (a non-superuser PATCHing one *to* editorial would lock themselves out,
since the viewer-write queryset hides editorial rows from them)."""

import pytest
import rest_framework

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.tests.factories import ItemImageFactory

VIEWER_URL = "/api/v1/annotations/graphs/"
WRITE_ENDPOINTS = [
    ("authenticated_client", "/api/v1/annotations/graphs/"),
    ("management_client", "/api/v1/management/annotations/graphs/"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("client_fixture", "url"), WRITE_ENDPOINTS)
def test_update_cannot_move_annotation_to_another_image(request, client_fixture, url):
    client = request.getfixturevalue(client_fixture)
    graph = GraphFactory()
    original_image_id = graph.item_image_id

    response = client.patch(f"{url}{graph.id}/", data={"item_image": ItemImageFactory().id}, format="json")

    assert response.status_code == 400, response.data
    assert "item_image" in response.data
    graph.refresh_from_db()
    assert graph.item_image_id == original_image_id


@pytest.mark.django_db
@pytest.mark.parametrize(("client_fixture", "url"), WRITE_ENDPOINTS)
def test_update_accepts_the_annotations_own_image(request, client_fixture, url):
    client = request.getfixturevalue(client_fixture)
    graph = GraphFactory()

    response = client.patch(
        f"{url}{graph.id}/", data={"item_image": graph.item_image_id, "note": "edited"}, format="json"
    )

    assert response.status_code == 200, response.data
    graph.refresh_from_db()
    assert graph.note == "edited"


@pytest.mark.django_db
def test_non_superuser_patch_without_type_change_still_works(authenticated_client):
    graph = GraphFactory(annotation_type=Graph.AnnotationType.IMAGE)

    response = authenticated_client.patch(
        f"{VIEWER_URL}{graph.id}/",
        data={"note": "still editable"},
        format="json",
    )

    assert response.status_code == rest_framework.status.HTTP_200_OK, response.data
    graph.refresh_from_db()
    assert graph.note == "still editable"
    assert graph.annotation_type == Graph.AnnotationType.IMAGE


@pytest.mark.django_db
@pytest.mark.parametrize(("client_fixture", "url"), WRITE_ENDPOINTS)
def test_update_cannot_change_an_annotations_kind(request, client_fixture, url):
    client = request.getfixturevalue(client_fixture)
    graph = GraphFactory(annotation_type=Graph.AnnotationType.IMAGE)

    changed = client.patch(f"{url}{graph.id}/", data={"annotation_type": "text"}, format="json")
    same = client.patch(f"{url}{graph.id}/", data={"annotation_type": "image", "note": "kept"}, format="json")

    assert changed.status_code == 400, changed.data
    assert "annotation_type" in changed.data
    assert same.status_code == 200, same.data
    graph.refresh_from_db()
    assert graph.annotation_type == Graph.AnnotationType.IMAGE


@pytest.mark.django_db
def test_the_model_refuses_a_kind_change():
    graph = GraphFactory(annotation_type=Graph.AnnotationType.IMAGE)
    graph = Graph.objects.get(pk=graph.pk)

    graph.annotation_type = Graph.AnnotationType.EDITORIAL
    with pytest.raises(ValueError, match="fixed when it is created"):
        graph.save()

    graph.annotation_type = Graph.AnnotationType.IMAGE
    graph.note = "same kind saves"
    graph.save()
