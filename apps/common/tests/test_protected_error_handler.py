"""ProtectedError → 409 via the project exception handler (#160).

Deleting a record still referenced through on_delete=PROTECT used to escape as
an unhandled 500. It is a data conflict: the handler answers 409 with a
`detail` naming the blockers.
"""

import pytest
import rest_framework

from apps.annotations.tests.factories import GraphFactory
from apps.scribes.models import Hand
from apps.scribes.tests.factories import HandFactory

HANDS_URL = "/api/v1/management/scribes/hands/"


@pytest.mark.django_db
def test_delete_blocked_by_protect_returns_409(management_client):
    graph = GraphFactory()

    response = management_client.delete(f"{HANDS_URL}{graph.hand_id}/")

    assert response.status_code == rest_framework.status.HTTP_409_CONFLICT, response.data
    assert response.data["detail"] == "Cannot delete: still referenced by 1 graph."
    assert Hand.objects.filter(id=graph.hand_id).exists()


@pytest.mark.django_db
def test_409_detail_pluralizes_blocker_count(management_client):
    graph = GraphFactory()
    GraphFactory(item_image=graph.item_image, allograph=graph.allograph, hand=graph.hand)

    response = management_client.delete(f"{HANDS_URL}{graph.hand_id}/")

    assert response.status_code == rest_framework.status.HTTP_409_CONFLICT
    assert response.data["detail"] == "Cannot delete: still referenced by 2 graphs."


@pytest.mark.django_db
def test_unreferenced_delete_still_works(management_client):
    hand = HandFactory()

    response = management_client.delete(f"{HANDS_URL}{hand.id}/")

    assert response.status_code == rest_framework.status.HTTP_204_NO_CONTENT
    assert not Hand.objects.filter(id=hand.id).exists()


@pytest.mark.django_db
def test_other_exceptions_still_handled_by_drf(management_client):
    response = management_client.delete(f"{HANDS_URL}999999/")

    assert response.status_code == rest_framework.status.HTTP_404_NOT_FOUND
