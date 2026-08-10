"""Non-superusers must not be able to PATCH an annotation to editorial (#158).

perform_create already blocks creating editorial graphs; without the matching
update guard, a non-superuser could flip annotation_type on an existing graph
and silently lock themselves out — the viewer-write queryset excludes editorial
rows for them, so the row would 404 on every subsequent request of theirs.
"""

import pytest
import rest_framework

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory

VIEWER_URL = "/api/v1/annotations/graphs/"


@pytest.mark.django_db
def test_non_superuser_cannot_patch_annotation_to_editorial(authenticated_client):
    graph = GraphFactory(annotation_type=Graph.AnnotationType.IMAGE)

    response = authenticated_client.patch(
        f"{VIEWER_URL}{graph.id}/",
        data={"annotation_type": Graph.AnnotationType.EDITORIAL},
        format="json",
    )

    assert response.status_code == rest_framework.status.HTTP_403_FORBIDDEN, response.data
    graph.refresh_from_db()
    assert graph.annotation_type == Graph.AnnotationType.IMAGE


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
def test_superuser_can_patch_annotation_to_editorial(management_client):
    graph = GraphFactory(annotation_type=Graph.AnnotationType.IMAGE)

    response = management_client.patch(
        f"{VIEWER_URL}{graph.id}/",
        data={"annotation_type": Graph.AnnotationType.EDITORIAL},
        format="json",
    )

    assert response.status_code == rest_framework.status.HTTP_200_OK, response.data
    graph.refresh_from_db()
    assert graph.annotation_type == Graph.AnnotationType.EDITORIAL
