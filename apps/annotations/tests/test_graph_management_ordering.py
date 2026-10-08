import pytest

from apps.annotations.tests.factories import GraphFactory

MANAGEMENT_URL = "/api/v1/management/annotations/graphs/"


@pytest.mark.django_db
@pytest.mark.parametrize("trashed", [False, True])
def test_graphs_sort_by_hand_name(management_client, trashed):
    second = GraphFactory(hand__name="B hand")
    first = GraphFactory(hand__name="A hand")
    if trashed:
        # Newest deletion first is the trash's default order, so trash `first` first.
        first.soft_delete()
        second.soft_delete()

    params = {"ordering": "hand__name", **({"deleted": "true"} if trashed else {})}
    rows = management_client.get(MANAGEMENT_URL, params).data["results"]

    assert [row["id"] for row in rows] == [first.id, second.id]
