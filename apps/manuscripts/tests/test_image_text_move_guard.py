import pytest

from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory

URL = "/api/v1/manuscripts/management/image-texts/"


@pytest.mark.django_db
def test_update_cannot_move_text_to_another_image(management_client):
    text = ImageTextFactory()
    original_image_id = text.item_image_id

    response = management_client.patch(f"{URL}{text.id}/", data={"item_image": ItemImageFactory().id}, format="json")

    assert response.status_code == 400, response.data
    assert "item_image" in response.data
    text.refresh_from_db()
    assert text.item_image_id == original_image_id


@pytest.mark.django_db
def test_update_accepts_the_texts_own_image(management_client):
    text = ImageTextFactory()

    response = management_client.patch(
        f"{URL}{text.id}/", data={"item_image": text.item_image_id, "language": "la"}, format="json"
    )

    assert response.status_code == 200, response.data
    text.refresh_from_db()
    assert text.language == "la"
