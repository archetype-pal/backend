from datetime import timedelta

from django.utils import timezone
import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory

MANAGEMENT_URL = "/api/v1/management/annotations/graphs/"


@pytest.mark.django_db
def test_trash_lists_newest_deletion_first_then_by_id(management_client):
    same_moment = GraphFactory.create_batch(3)
    newest = GraphFactory()
    now = timezone.now()
    Graph.all_objects.filter(pk__in=[graph.pk for graph in same_moment]).update(deleted_at=now)
    Graph.all_objects.filter(pk=newest.pk).update(deleted_at=now + timedelta(minutes=1))

    rows = management_client.get(MANAGEMENT_URL, {"deleted": "true"}).data["results"]

    assert [row["id"] for row in rows] == [newest.id] + sorted(graph.id for graph in same_moment)
