import pytest
import rest_framework
from rest_framework.test import APITestCase

from apps.annotations.models import Graph, GraphComponent
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory, ComponentFactory, FeatureFactory, PositionFactory
from apps.users.tests.factories import SuperuserFactory


class TestGraphViewSet(APITestCase):
    def setUp(self):
        superuser = SuperuserFactory()
        self.client.force_authenticate(user=superuser)
        self.item_image = ItemImageFactory()
        self.item_part = self.item_image.item_part
        self.allograph = AllographFactory()
        self.hand = HandFactory(item_part=self.item_part)

        self.graphs = GraphFactory.create_batch(3, item_image=self.item_image, allograph=self.allograph, hand=self.hand)

        # adds a structure of components and features
        self.features = FeatureFactory.create_batch(4)
        self.components = ComponentFactory.create_batch(3)
        for component in self.components[:2]:
            gc = GraphComponent.objects.create(graph=self.graphs[0], component=component)
            gc.features.set(self.features)

        self.positions = PositionFactory.create_batch(3)

    def test_list_graphs(self):
        response = self.client.get("/api/v1/manuscripts/graphs/")
        assert response.status_code == rest_framework.status.HTTP_200_OK, response.data
        assert len(response.data) == 3, response.data
        assert len(response.data[0]["graphcomponent_set"]) == 2, response.data
        assert len(response.data[0]["graphcomponent_set"][0]["features"]) == 4, response.data

        first_graph = next(item for item in response.data if item["id"] == self.graphs[0].id)
        second_graph = next(item for item in response.data if item["id"] == self.graphs[1].id)

        assert first_graph["num_features"] == 8, response.data
        assert first_graph["is_described"] is True, response.data
        assert second_graph["num_features"] == 0, response.data
        assert second_graph["is_described"] is False, response.data

    def test_filter_graphs(self):
        other_item_image = ItemImageFactory()
        GraphFactory.create_batch(4, item_image=other_item_image, allograph=self.allograph)

        response = self.client.get("/api/v1/manuscripts/graphs/")
        assert response.status_code == rest_framework.status.HTTP_200_OK, response.data
        assert len(response.data) == 7, response.data

        response = self.client.get(f"/api/v1/manuscripts/graphs/?item_image={other_item_image.id}")
        assert response.status_code == rest_framework.status.HTTP_200_OK, response.data
        assert len(response.data) == 4, response.data

    def test_public_create_graph_is_not_allowed(self):
        response = self.client.post(
            "/api/v1/manuscripts/graphs/",
            data={
                "item_image": self.item_image.id,
                "annotation": {"x": 0, "y": 0, "width": 100, "height": 100},
                "allograph": self.allograph.id,
                "hand": self.hand.id,
                "graphcomponent_set": [
                    {
                        "component": self.components[0].id,
                        "features": [self.features[0].id, self.features[1].id],
                    },
                    {
                        "component": self.components[1].id,
                        "features": [self.features[2].id, self.features[3].id],
                    },
                ],
                "positions": [self.positions[0].id, self.positions[1].id],
            },
            format="json",
        )
        assert response.status_code == rest_framework.status.HTTP_405_METHOD_NOT_ALLOWED, response.data

    def test_viewer_create_standard_graph_with_note(self):
        response = self.client.post(
            "/api/v1/annotations/graphs/",
            data={
                "item_image": self.item_image.id,
                "annotation": {"x": 0, "y": 0, "width": 100, "height": 100},
                "annotation_type": Graph.AnnotationType.IMAGE,
                "allograph": self.allograph.id,
                "hand": self.hand.id,
                "note": "Visible standard note",
                "internal_note": "should be discarded",
                "graphcomponent_set": [],
                "positions": [],
            },
            format="json",
        )

        assert response.status_code == rest_framework.status.HTTP_201_CREATED, response.data
        assert response.data["annotation_type"] == Graph.AnnotationType.IMAGE
        assert response.data["note"] == "Visible standard note"
        assert response.data["internal_note"] == ""

        created_graph = Graph.objects.get(id=response.data["id"])
        assert created_graph.note == "Visible standard note"
        assert created_graph.internal_note == ""

    def test_viewer_create_standard_graph_requires_allograph_and_hand(self):
        response = self.client.post(
            "/api/v1/annotations/graphs/",
            data={
                "item_image": self.item_image.id,
                "annotation": {"x": 0, "y": 0, "width": 100, "height": 100},
                "annotation_type": Graph.AnnotationType.IMAGE,
                "graphcomponent_set": [],
                "positions": [],
            },
            format="json",
        )

        assert response.status_code == rest_framework.status.HTTP_400_BAD_REQUEST, response.data
        assert "allograph" in response.data
        assert "hand" in response.data

    def test_viewer_create_editorial_graph_without_allograph_or_hand(self):
        response = self.client.post(
            "/api/v1/annotations/graphs/",
            data={
                "item_image": self.item_image.id,
                "annotation": {"x": 0, "y": 0, "width": 100, "height": 100},
                "annotation_type": Graph.AnnotationType.EDITORIAL,
                "note": "should be discarded",
                "internal_note": "Private editorial note",
                "graphcomponent_set": [],
                "positions": [],
            },
            format="json",
        )

        assert response.status_code == rest_framework.status.HTTP_201_CREATED, response.data
        assert response.data["annotation_type"] == Graph.AnnotationType.EDITORIAL
        assert response.data["allograph"] is None
        assert response.data["hand"] is None
        assert response.data["note"] == ""
        assert response.data["internal_note"] == "Private editorial note"

        created_graph = Graph.objects.get(id=response.data["id"])
        assert created_graph.allograph is None
        assert created_graph.hand is None
        assert created_graph.note == ""
        assert created_graph.internal_note == "Private editorial note"

    def test_anonymous_graph_list_hides_editorial_graphs(self):
        editorial = GraphFactory(
            item_image=self.item_image,
            annotation_type=Graph.AnnotationType.EDITORIAL,
            allograph=None,
            hand=None,
        )

        self.client.force_authenticate(user=None)
        response = self.client.get(f"/api/v1/manuscripts/graphs/?item_image={self.item_image.id}")

        assert response.status_code == rest_framework.status.HTTP_200_OK, response.data
        assert editorial.id not in {item["id"] for item in response.data}

    def test_management_create_graph(self):
        response = self.client.post(
            "/api/v1/management/annotations/graphs/",
            data={
                "item_image": self.item_image.id,
                "annotation": {"x": 0, "y": 0, "width": 100, "height": 100},
                "allograph": self.allograph.id,
                "hand": self.hand.id,
                "graphcomponent_set": [
                    {
                        "component": self.components[0].id,
                        "features": [self.features[0].id, self.features[1].id],
                    },
                    {
                        "component": self.components[1].id,
                        "features": [self.features[2].id, self.features[3].id],
                    },
                ],
                "positions": [self.positions[0].id, self.positions[1].id],
            },
            format="json",
        )
        assert response.status_code == rest_framework.status.HTTP_201_CREATED, response.data
        assert len(response.data["graphcomponent_set"]) == 2, response.data
        assert len(response.data["graphcomponent_set"][0]["features"]) == 2, response.data

        created_graph = Graph.objects.get(id=response.data["id"])
        assert created_graph.item_image == self.item_image
        assert created_graph.annotation == {"x": 0, "y": 0, "width": 100, "height": 100}
        assert created_graph.allograph == self.allograph
        assert created_graph.hand == self.hand
        assert created_graph.graphcomponent_set.count() == 2
        assert created_graph.graphcomponent_set.first().features.count() == 2
        assert created_graph.graphcomponent_set.last().features.count() == 2
        assert created_graph.positions.count() == 2
        assert response.data["num_features"] == 4, response.data
        assert response.data["is_described"] is True, response.data

    @pytest.mark.skip(reason="Graph create with empty components/positions: behaviour not yet decided.")
    def test_create_graph_with_no_positions_nor_components(self):
        response = self.client.post(
            "/api/v1/manuscripts/graphs/",
            data={
                "item_image": self.item_image.id,
                "annotation": {"x": 0, "y": 0, "width": 100, "height": 100},
                "allograph": self.allograph.id,
                "hand": self.hand.id,
                "graphcomponent_set": [],
                "positions": [],
            },
            format="json",
        )
        assert response.status_code == rest_framework.status.HTTP_201_CREATED, response.data
        assert len(response.data["graphcomponent_set"]) == 0, response.data
        assert len(response.data["positions"]) == 0, response.data

        created_graph = Graph.objects.get(id=response.data["id"])
        assert created_graph.item_image == self.item_image
        assert created_graph.annotation == {"x": 0, "y": 0, "width": 100, "height": 100}
        assert created_graph.allograph == self.allograph
        assert created_graph.hand == self.hand
        assert created_graph.graphcomponent_set.count() == 0
        assert created_graph.positions.count() == 0

    def test_graph_with_components_but_no_features_is_undescribed(self):
        graph = GraphFactory(item_image=self.item_image, allograph=self.allograph, hand=self.hand)
        GraphComponent.objects.create(graph=graph, component=self.components[0])
        GraphComponent.objects.create(graph=graph, component=self.components[1])

        response = self.client.get(f"/api/v1/manuscripts/graphs/?item_image={self.item_image.id}")
        assert response.status_code == rest_framework.status.HTTP_200_OK, response.data

        created = next(item for item in response.data if item["id"] == graph.id)
        assert len(created["graphcomponent_set"]) == 2, response.data
        assert created["num_features"] == 0, response.data
        assert created["is_described"] is False, response.data
