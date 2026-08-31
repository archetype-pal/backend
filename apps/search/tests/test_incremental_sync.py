from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import override_settings
import pytest

from apps.annotations.models import Graph, GraphComponent
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.services import IndexingService
from apps.search.tasks import delete_search_documents, sync_search_documents
from apps.search.types import IndexType


class TestMeilisearchIndexWriterIncremental:
    def test_update_documents_calls_sdk_update(self):
        writer = MeilisearchIndexWriter()
        writer._client = MagicMock()
        mock_index = writer._client.index.return_value

        docs = [{"id": 1, "name": "foo"}, {"id": 2, "name": "bar"}]
        writer.update_documents(IndexType.GRAPHS, docs)

        mock_index.update_documents.assert_called_once_with(docs, primary_key="id")

    def test_delete_documents_calls_sdk_delete(self):
        writer = MeilisearchIndexWriter()
        writer._client = MagicMock()
        mock_index = writer._client.index.return_value

        writer.delete_documents(IndexType.GRAPHS, [1, 2])

        mock_index.delete_documents.assert_called_once_with(["1", "2"])

    def test_empty_lists_no_op(self):
        writer = MeilisearchIndexWriter()
        writer._client = MagicMock()

        writer.update_documents(IndexType.GRAPHS, [])
        writer.delete_documents(IndexType.GRAPHS, [])

        writer._client.index.assert_not_called()


class TestIndexingServiceIncremental:
    def test_update_documents_by_ids_indexes_found_objects(self, monkeypatch):
        fake_writer = MagicMock()
        service = IndexingService(writer=fake_writer)

        fake_registration = SimpleNamespace(
            builder=lambda obj: [{"id": obj.id, "title": f"Doc {obj.id}"}],
        )
        monkeypatch.setattr(
            "apps.search.services.get_registration",
            lambda index_type: fake_registration if index_type == IndexType.GRAPHS else None,
        )

        fake_obj1 = SimpleNamespace(id=1, pk=1)
        fake_obj2 = SimpleNamespace(id=2, pk=2)
        fake_qs = MagicMock()
        fake_qs.filter.return_value = [fake_obj1, fake_obj2]

        monkeypatch.setattr(
            "apps.search.services.get_queryset_for_index",
            lambda index_type: fake_qs if index_type == IndexType.GRAPHS else None,
        )

        indexed_count = service.update_documents_by_ids(IndexType.GRAPHS, [1, 2])

        assert indexed_count == 2
        fake_writer.update_documents.assert_called_once_with(
            IndexType.GRAPHS,
            [{"id": 1, "title": "Doc 1"}, {"id": 2, "title": "Doc 2"}],
        )
        fake_writer.delete_documents.assert_not_called()

    def test_update_documents_by_ids_deletes_missing_or_trashed_ids(self, monkeypatch):
        fake_writer = MagicMock()
        service = IndexingService(writer=fake_writer)

        fake_registration = SimpleNamespace(
            builder=lambda obj: [{"id": obj.id}],
        )
        monkeypatch.setattr(
            "apps.search.services.get_registration",
            lambda index_type: fake_registration if index_type == IndexType.GRAPHS else None,
        )

        # Only ID 1 is returned from DB; ID 2 was trashed/deleted so not returned
        fake_obj1 = SimpleNamespace(id=1, pk=1)
        fake_qs = MagicMock()
        fake_qs.filter.return_value = [fake_obj1]

        monkeypatch.setattr(
            "apps.search.services.get_queryset_for_index",
            lambda index_type: fake_qs if index_type == IndexType.GRAPHS else None,
        )

        indexed_count = service.update_documents_by_ids(IndexType.GRAPHS, [1, 2])

        assert indexed_count == 1
        fake_writer.update_documents.assert_called_once_with(IndexType.GRAPHS, [{"id": 1}])
        fake_writer.delete_documents.assert_called_once_with(IndexType.GRAPHS, [2])

    @pytest.mark.django_db
    def test_update_documents_by_ids_indexes_real_item_image(self):
        """Unlike the GRAPHS tests above (which fake get_registration/get_queryset_for_index),
        this exercises the real ITEM_IMAGES registry entry, builder, and DB queryset."""
        from apps.annotations.tests.factories import GraphComponentFactory
        from apps.manuscripts.tests.factories import ItemImageFactory

        img = ItemImageFactory(locus="face")
        GraphComponentFactory(graph__item_image=img)

        fake_writer = MagicMock()
        service = IndexingService(writer=fake_writer)

        indexed_count = service.update_documents_by_ids(IndexType.ITEM_IMAGES, [img.pk])

        assert indexed_count == 1
        fake_writer.delete_documents.assert_not_called()
        (called_index_type, docs), _ = fake_writer.update_documents.call_args
        assert called_index_type == IndexType.ITEM_IMAGES
        assert docs[0]["id"] == img.id
        assert docs[0]["number_of_annotations"] == 1

    def test_delete_documents_by_ids_calls_writer(self):
        fake_writer = MagicMock()
        service = IndexingService(writer=fake_writer)

        service.delete_documents_by_ids(IndexType.GRAPHS, [10, 20])

        fake_writer.delete_documents.assert_called_once_with(IndexType.GRAPHS, [10, 20])


class TestCeleryTasksIncremental:
    def test_sync_search_documents_task(self, monkeypatch):
        fake_indexing = MagicMock()
        fake_indexing.update_documents_by_ids.return_value = 2
        monkeypatch.setattr("apps.search.tasks.IndexingService", lambda: fake_indexing)

        result = sync_search_documents.run("graphs", [1, 2])

        assert result == {"action": "sync_documents", "index_type": "graphs", "indexed": 2, "pks": [1, 2]}
        fake_indexing.update_documents_by_ids.assert_called_once_with(IndexType.GRAPHS, [1, 2])

    def test_delete_search_documents_task(self, monkeypatch):
        fake_indexing = MagicMock()
        monkeypatch.setattr("apps.search.tasks.IndexingService", lambda: fake_indexing)

        result = delete_search_documents.run("graphs", [5])

        assert result == {"action": "delete_documents", "index_type": "graphs", "pks": [5]}
        fake_indexing.delete_documents_by_ids.assert_called_once_with(IndexType.GRAPHS, [5])


@pytest.mark.django_db
class TestSearchSignals:
    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_save_enqueues_sync_task_and_item_image(self, monkeypatch):
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        graph = Graph(
            id=999, item_image_id=123, annotation_type=Graph.AnnotationType.TEXT, annotation={"type": "Polygon"}
        )
        from apps.search.signals import sync_graph_on_save

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("django.db.transaction.on_commit", lambda callback: callback())
            sync_graph_on_save(sender=Graph, instance=graph)

        assert mock_sync_task.call_count == 2
        mock_sync_task.assert_any_call("graphs", [999])
        mock_sync_task.assert_any_call("item-images", [123])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_soft_delete_enqueues_delete_task_and_item_image(self, monkeypatch):
        from django.utils import timezone

        mock_delete_task = MagicMock()
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.delete_search_documents.delay", mock_delete_task)
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        graph = Graph(
            id=999,
            item_image_id=123,
            annotation_type=Graph.AnnotationType.TEXT,
            annotation={"type": "Polygon"},
            deleted_at=timezone.now(),
        )
        from apps.search.signals import sync_graph_on_save

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("django.db.transaction.on_commit", lambda callback: callback())
            sync_graph_on_save(sender=Graph, instance=graph)

        mock_delete_task.assert_called_once_with("graphs", [999])
        mock_sync_task.assert_called_once_with("item-images", [123])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_component_save_enqueues_parent_graph_sync(self, monkeypatch):
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        gc = GraphComponent(id=1, graph_id=42)
        gc.graph = Graph(id=42, item_image_id=456)
        from apps.search.signals import sync_graph_on_component_save

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("django.db.transaction.on_commit", lambda callback: callback())
            sync_graph_on_component_save(sender=GraphComponent, instance=gc)

        assert mock_sync_task.call_count == 2
        mock_sync_task.assert_any_call("graphs", [42])
        mock_sync_task.assert_any_call("item-images", [456])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_delete_enqueues_delete_task(self, monkeypatch):
        mock_delete_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.delete_search_documents.delay", mock_delete_task)

        graph = Graph(id=777)
        from apps.search.signals import sync_graph_on_delete

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("django.db.transaction.on_commit", lambda callback: callback())
            sync_graph_on_delete(sender=Graph, instance=graph)

        mock_delete_task.assert_called_once_with("graphs", [777])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_component_delete_enqueues_parent_graph_sync(self, monkeypatch):
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        gc = GraphComponent(id=2, graph_id=88)
        gc.graph = Graph(id=88, item_image_id=789)
        from apps.search.signals import sync_graph_on_component_delete

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("django.db.transaction.on_commit", lambda callback: callback())
            sync_graph_on_component_delete(sender=GraphComponent, instance=gc)

        assert mock_sync_task.call_count == 2
        mock_sync_task.assert_any_call("graphs", [88])
        mock_sync_task.assert_any_call("item-images", [789])

    @override_settings(SEARCH_AUTO_REINDEX=False)
    def test_signals_disabled_when_search_auto_reindex_false(self, monkeypatch):
        mock_sync_task = MagicMock()
        mock_delete_task = MagicMock()
        mock_reindex_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)
        monkeypatch.setattr("apps.search.signals.delete_search_documents.delay", mock_delete_task)
        monkeypatch.setattr("apps.search.signals.reindex_search_index.delay", mock_reindex_task)

        graph = Graph(
            id=999, item_image_id=123, annotation_type=Graph.AnnotationType.TEXT, annotation={"type": "Polygon"}
        )
        from apps.manuscripts.models import MsDescArea
        from apps.search.signals import reindex_item_parts_on_msdesc_area_save, sync_graph_on_save

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("django.db.transaction.on_commit", lambda callback: callback())
            sync_graph_on_save(sender=Graph, instance=graph)
            reindex_item_parts_on_msdesc_area_save(sender=MsDescArea, instance=MsDescArea(id=10))

        mock_sync_task.assert_not_called()
        mock_delete_task.assert_not_called()
        mock_reindex_task.assert_not_called()
