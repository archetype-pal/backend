import pytest

from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.tests.factories import ItemImageFactory

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
