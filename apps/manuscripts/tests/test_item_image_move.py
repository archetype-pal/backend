import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.tests.factories import ItemImageFactory, ItemPartFactory
from apps.scribes.tests.factories import HandFactory

pytestmark = pytest.mark.django_db

BASE_URL = "/api/v1/manuscripts/management/item-images/"


def _move(client, image, part):
    return client.patch(f"{BASE_URL}{image.pk}/", {"item_part": part.pk}, format="json")


def test_image_without_hand_attributions_moves(management_client):
    image = ItemImageFactory()
    GraphFactory(item_image=image, annotation_type=Graph.AnnotationType.TEXT, allograph=None, hand=None)
    target = ItemPartFactory()

    response = _move(management_client, image, target)

    assert response.status_code == 200, response.data
    image.refresh_from_db()
    assert image.item_part_id == target.pk


def test_annotation_with_a_hand_blocks_the_move(management_client):
    image = ItemImageFactory()
    original_part_id = image.item_part_id
    GraphFactory(item_image=image)

    response = _move(management_client, image, ItemPartFactory())

    assert response.status_code == 400, response.data
    assert "Annotations with a hand: 1." in response.data["item_part"][0]
    image.refresh_from_db()
    assert image.item_part_id == original_part_id


def test_trashed_annotation_with_a_hand_blocks_the_move(management_client):
    image = ItemImageFactory()
    GraphFactory(item_image=image).soft_delete()

    response = _move(management_client, image, ItemPartFactory())

    assert response.status_code == 400, response.data
    assert "Annotations with a hand: 1 (1 in the trash)." in response.data["item_part"][0]


def test_hand_link_blocks_the_move(management_client):
    image = ItemImageFactory()
    hand = HandFactory(item_part=image.item_part, name="Main Hand")
    hand.item_part_images.add(image)

    response = _move(management_client, image, ItemPartFactory())

    assert response.status_code == 400, response.data
    assert "Linked hands: Main Hand." in response.data["item_part"][0]


def test_sending_the_current_part_is_not_a_move(management_client):
    image = ItemImageFactory()
    GraphFactory(item_image=image)

    response = management_client.patch(
        f"{BASE_URL}{image.pk}/", {"item_part": image.item_part_id, "locus": "f.3r"}, format="json"
    )

    assert response.status_code == 200, response.data
    image.refresh_from_db()
    assert image.locus == "f.3r"
