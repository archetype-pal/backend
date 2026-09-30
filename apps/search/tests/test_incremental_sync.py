import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import override_settings
from meilisearch.errors import MeilisearchApiError, MeilisearchError
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
            parent_id_field=None,
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
            parent_id_field=None,
        )
        monkeypatch.setattr(
            "apps.search.services.get_registration",
            lambda index_type: fake_registration if index_type == IndexType.GRAPHS else None,
        )

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
    @pytest.fixture(autouse=True)
    def _reset_pending_graph_syncs(self):
        """These tests call signal receivers directly, bypassing the request
        cycle that clears apps.search.signals._pending_graph_syncs in
        production (via request_finished) — reset it here so state can't leak
        between tests reusing the same thread."""
        from apps.search import signals

        signals._pending_graph_syncs.ids = None
        yield
        signals._pending_graph_syncs.ids = None

    @pytest.fixture
    def run_on_commit(self, monkeypatch):
        """Collects on_commit callbacks instead of running them inline, so
        tests can trigger "the transaction commits" as its own explicit step
        — matching real Django semantics, where every callback registered
        during one transaction fires only once that transaction actually
        commits. Firing them inline as they're registered would defeat the
        pending-graph-syncs coalescing this whole class is testing."""
        callbacks: list = []
        monkeypatch.setattr("django.db.transaction.on_commit", lambda callback: callbacks.append(callback))

        def _fire():
            pending, callbacks[:] = list(callbacks), []
            for callback in pending:
                callback()

        return _fire

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_save_enqueues_sync_task_and_item_image(self, monkeypatch, run_on_commit):
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        graph = Graph(
            id=999, item_image_id=123, annotation_type=Graph.AnnotationType.TEXT, annotation={"type": "Polygon"}
        )
        from apps.search.signals import sync_graph_on_save

        sync_graph_on_save(sender=Graph, instance=graph)
        run_on_commit()

        assert mock_sync_task.call_count == 2
        mock_sync_task.assert_any_call("graphs", [999])
        mock_sync_task.assert_any_call("item-images", [123])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_soft_delete_enqueues_delete_task_and_item_image(self, monkeypatch, run_on_commit):
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

        sync_graph_on_save(sender=Graph, instance=graph)
        run_on_commit()

        mock_delete_task.assert_called_once_with("graphs", [999])
        mock_sync_task.assert_called_once_with("item-images", [123])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_component_save_enqueues_parent_graph_sync(self, monkeypatch, run_on_commit):
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        gc = GraphComponent(id=1, graph_id=42)
        gc.graph = Graph(id=42, item_image_id=456)
        from apps.search.signals import sync_graph_on_component_save

        sync_graph_on_component_save(sender=GraphComponent, instance=gc)
        run_on_commit()

        assert mock_sync_task.call_count == 2
        mock_sync_task.assert_any_call("graphs", [42])
        mock_sync_task.assert_any_call("item-images", [456])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_save_then_component_save_coalesces_into_one_sync(self, monkeypatch, run_on_commit):
        """GraphWriteMixin saves the Graph, then replaces its components — each
        touching the same graph_id, inside the same transaction. Only one
        enqueue per index should happen."""
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        graph = Graph(
            id=42, item_image_id=456, annotation_type=Graph.AnnotationType.TEXT, annotation={"type": "Polygon"}
        )
        gc = GraphComponent(id=1, graph_id=42)
        from apps.search.signals import sync_graph_on_component_save, sync_graph_on_save

        sync_graph_on_save(sender=Graph, instance=graph)
        sync_graph_on_component_save(sender=GraphComponent, instance=gc)
        run_on_commit()

        assert mock_sync_task.call_count == 2
        mock_sync_task.assert_any_call("graphs", [42])
        mock_sync_task.assert_any_call("item-images", [456])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_component_save_skips_graph_lookup_once_parent_sync_is_pending(self, monkeypatch, run_on_commit):
        """Once the parent Graph's own save has claimed graph_id, a component
        handler for the same graph must not touch instance.graph at all —
        proven here by giving it a `.graph` that raises if accessed."""
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        graph = Graph(
            id=42, item_image_id=456, annotation_type=Graph.AnnotationType.TEXT, annotation={"type": "Polygon"}
        )

        class _ExplodingGraphAccess:
            graph_id = 42

            @property
            def graph(self):
                raise AssertionError("instance.graph should not be accessed when parent sync is pending")

        gc = _ExplodingGraphAccess()
        from apps.search.signals import sync_graph_on_component_save, sync_graph_on_save

        sync_graph_on_save(sender=Graph, instance=graph)
        sync_graph_on_component_save(sender=GraphComponent, instance=gc)
        run_on_commit()

        assert mock_sync_task.call_count == 2

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_delete_enqueues_delete_task(self, monkeypatch, run_on_commit):
        mock_delete_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.delete_search_documents.delay", mock_delete_task)

        graph = Graph(id=777)
        from apps.search.signals import sync_graph_on_delete

        sync_graph_on_delete(sender=Graph, instance=graph)
        run_on_commit()

        mock_delete_task.assert_called_once_with("graphs", [777])

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_graph_component_delete_enqueues_parent_graph_sync(self, monkeypatch, run_on_commit):
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        gc = GraphComponent(id=2, graph_id=88)
        gc.graph = Graph(id=88, item_image_id=789)
        from apps.search.signals import sync_graph_on_component_delete

        sync_graph_on_component_delete(sender=GraphComponent, instance=gc)
        run_on_commit()

        assert mock_sync_task.call_count == 2
        mock_sync_task.assert_any_call("graphs", [88])
        mock_sync_task.assert_any_call("item-images", [789])

    @override_settings(SEARCH_AUTO_REINDEX=False)
    def test_signals_disabled_when_search_auto_reindex_false(self, monkeypatch, run_on_commit):
        mock_sync_task = MagicMock()
        mock_delete_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)
        monkeypatch.setattr("apps.search.signals.delete_search_documents.delay", mock_delete_task)

        graph = Graph(
            id=999, item_image_id=123, annotation_type=Graph.AnnotationType.TEXT, annotation={"type": "Polygon"}
        )
        from apps.manuscripts.models import MsDescArea
        from apps.search.signals import sync_dependent_documents, sync_graph_on_save

        sync_graph_on_save(sender=Graph, instance=graph)
        sync_dependent_documents(MsDescArea(id=10, item_part_id=5))
        run_on_commit()

        mock_sync_task.assert_not_called()
        mock_delete_task.assert_not_called()

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_same_graph_saved_again_in_a_later_transaction_enqueues_again(self, monkeypatch, run_on_commit):
        """Regression test for a thread-local lockout: once a graph_id's own
        on_commit callback has actually run, a later save of that same graph
        on the same thread — a separate transaction, e.g. a management
        command or Celery task revisiting it — must schedule its own sync
        rather than being silently dropped because the id was never cleared."""
        mock_sync_task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", mock_sync_task)

        graph = Graph(
            id=42, item_image_id=456, annotation_type=Graph.AnnotationType.TEXT, annotation={"type": "Polygon"}
        )
        from apps.search.signals import sync_graph_on_save

        sync_graph_on_save(sender=Graph, instance=graph)
        run_on_commit()
        assert mock_sync_task.call_count == 2
        mock_sync_task.reset_mock()

        # A second transaction on the same graph and thread with no
        # request_finished between: a Celery worker or management command.
        sync_graph_on_save(sender=Graph, instance=graph)
        run_on_commit()

        assert mock_sync_task.call_count == 2
        mock_sync_task.assert_any_call("graphs", [42])
        mock_sync_task.assert_any_call("item-images", [456])


def _api_error(code: str) -> MeilisearchApiError:
    """A Meilisearch API error carrying *code*, built the way the SDK builds one.

    Mirrors the helper in `test_services.py`.
    """
    response = MagicMock()
    response.status_code = 400
    response.text = json.dumps({"message": f"simulated {code}", "code": code, "type": "invalid_request"})
    return MeilisearchApiError("", response)


class TestDeleteDocumentsByFilter:
    def test_passes_the_filter_to_the_sdk(self):
        writer = MeilisearchIndexWriter()
        writer._client = MagicMock()

        writer.delete_documents_by_filter(IndexType.CLAUSES, "image_text IN [1, 2]")

        writer._client.index.return_value.delete_documents.assert_called_once_with(filter="image_text IN [1, 2]")

    def test_empty_filter_is_a_no_op(self):
        writer = MeilisearchIndexWriter()
        writer._client = MagicMock()

        writer.delete_documents_by_filter(IndexType.CLAUSES, "")

        writer._client.index.assert_not_called()

    def test_a_failed_delete_task_raises_rather_than_passing_silently(self):
        """Meilisearch accepts a filter naming a non-filterable attribute and
        then fails the task asynchronously, so without waiting nothing reports it.
        """
        writer = MeilisearchIndexWriter()
        writer._client = MagicMock()
        writer._client.wait_for_task.return_value = SimpleNamespace(
            status="failed", error={"code": "invalid_document_filter"}
        )

        with pytest.raises(MeilisearchError):
            writer.delete_documents_by_filter(IndexType.CLAUSES, "image_text IN [1]")

    def test_other_api_errors_propagate(self):
        writer = MeilisearchIndexWriter()
        writer._client = MagicMock()
        writer._client.index.return_value.delete_documents.side_effect = _api_error("internal")

        with pytest.raises(MeilisearchApiError):
            writer.delete_documents_by_filter(IndexType.CLAUSES, "image_text IN [1]")


class TestFanOutIndexSync:
    """Indexes whose document ids are derived from the row (`42_0`)."""

    def test_documents_are_replaced_by_parent_filter_not_by_pk(self, monkeypatch):
        fake_writer = MagicMock()
        service = IndexingService(writer=fake_writer)
        monkeypatch.setattr(
            "apps.search.services.get_registration",
            lambda index_type: SimpleNamespace(
                builder=lambda obj: [{"id": f"{obj.id}_0"}],
                parent_id_field="image_text",
            ),
        )
        fake_qs = MagicMock()
        fake_qs.filter.return_value = [SimpleNamespace(id=7, pk=7)]
        monkeypatch.setattr("apps.search.services.get_queryset_for_index", lambda index_type: fake_qs)

        service.update_documents_by_ids(IndexType.CLAUSES, [7, 8])

        fake_writer.delete_documents_by_filter.assert_called_once_with(IndexType.CLAUSES, "image_text IN [7, 8]")
        fake_writer.update_documents.assert_called_once_with(IndexType.CLAUSES, [{"id": "7_0"}])
        # Row 8 produced no documents, but deleting it by pk could never have
        # matched `8_0` anyway — the filter above is what removed them.
        fake_writer.delete_documents.assert_not_called()

    def test_a_builder_error_leaves_the_existing_documents_alone(self, monkeypatch):
        """Documents are built before anything is deleted. The other order would
        let a malformed row destroy its documents with nothing to put back, and
        the task only autoretries Meilisearch communication errors.
        """
        fake_writer = MagicMock()
        service = IndexingService(writer=fake_writer)

        def boom(obj):
            raise ValueError("malformed TEI")

        monkeypatch.setattr(
            "apps.search.services.get_registration",
            lambda index_type: SimpleNamespace(builder=boom, parent_id_field="image_text"),
        )
        fake_qs = MagicMock()
        fake_qs.filter.return_value = [SimpleNamespace(id=7, pk=7)]
        monkeypatch.setattr("apps.search.services.get_queryset_for_index", lambda index_type: fake_qs)

        with pytest.raises(ValueError):
            service.update_documents_by_ids(IndexType.CLAUSES, [7])

        fake_writer.delete_documents_by_filter.assert_not_called()


class TestChunkedEnqueue:
    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_large_id_sets_are_split_into_chunks(self, monkeypatch):
        from apps.search.signals import SYNC_CHUNK_SIZE, _enqueue

        calls: list[tuple[str, list[int]]] = []
        monkeypatch.setattr(
            "apps.search.signals.sync_search_documents.delay", lambda segment, pks: calls.append((segment, pks))
        )

        _enqueue(IndexType.GRAPHS, range(SYNC_CHUNK_SIZE + 3))

        assert [len(pks) for _, pks in calls] == [SYNC_CHUNK_SIZE, 3]
        assert {segment for segment, _ in calls} == {"graphs"}

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_nothing_is_enqueued_for_an_empty_set(self, monkeypatch):
        from apps.search.signals import _enqueue

        task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", task)

        _enqueue(IndexType.GRAPHS, [])

        task.assert_not_called()

    @override_settings(SEARCH_AUTO_REINDEX=False)
    def test_the_kill_switch_stops_the_generic_path_too(self, monkeypatch):
        from apps.search.signals import _enqueue

        task = MagicMock()
        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", task)

        _enqueue(IndexType.GRAPHS, [1, 2, 3])

        task.assert_not_called()


@pytest.fixture
def enqueued(monkeypatch) -> list[tuple[str, list[int]]]:
    """Records `(segment, pks)` instead of queueing Celery tasks."""
    calls: list[tuple[str, list[int]]] = []
    monkeypatch.setattr(
        "apps.search.signals.sync_search_documents.delay",
        lambda segment, pks: calls.append((segment, sorted(pks))),
    )
    return calls


@pytest.mark.django_db
class TestDependencyDrivenSync:
    """Models wired through `dependencies.DEPENDENCIES`, driven by real writes.

    Rows a test does not want counted are created outside the capture block,
    since creating one is itself a write.
    """

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_new_image_syncs_itself_and_its_manuscript(self, enqueued, django_capture_on_commit_callbacks):
        from apps.manuscripts.tests.factories import ItemImageFactory, ItemPartFactory

        part = ItemPartFactory()
        with django_capture_on_commit_callbacks(execute=True):
            image = ItemImageFactory(item_part=part)

        assert ("item-images", [image.pk]) in enqueued
        # The manuscript card counts its images, so it changed too.
        assert ("item-parts", [part.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_editing_an_image_syncs_the_graphs_and_texts_that_copy_its_locus(
        self, enqueued, django_capture_on_commit_callbacks
    ):
        from apps.annotations.tests.factories import GraphFactory
        from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory

        image = ItemImageFactory()
        graph = GraphFactory(item_image=image)
        text = ImageTextFactory(item_image=image)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            image.locus = "f.2r"
            image.save(update_fields=["locus"])

        assert ("graphs", [graph.pk]) in enqueued
        assert ("texts", [text.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_saving_a_text_syncs_all_four_text_indexes(self, enqueued, django_capture_on_commit_callbacks):
        from apps.manuscripts.tests.factories import ImageTextFactory

        text = ImageTextFactory()
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            text.content = "<p>edited</p>"
            text.save(update_fields=["content"])

        for segment in ("texts", "people", "places"):
            assert (segment, [text.pk]) in enqueued
        assert any(segment == "clauses" for segment, _ in enqueued)

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_clause_sync_covers_the_other_text_on_the_same_image(self, enqueued, django_capture_on_commit_callbacks):
        """Clause documents borrow annotation ids from the image's other text,
        so editing one side rebuilds both."""
        from apps.manuscripts.models import ImageText
        from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory

        image = ItemImageFactory()
        transcription = ImageTextFactory(item_image=image, type=ImageText.Type.TRANSCRIPTION)
        translation = ImageTextFactory(item_image=image, type=ImageText.Type.TRANSLATION)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            transcription.content = "<p>edited</p>"
            transcription.save(update_fields=["content"])

        clause_calls = [pks for segment, pks in enqueued if segment == "clauses"]
        assert clause_calls == [sorted([transcription.pk, translation.pk])]

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_renaming_a_hand_syncs_the_graphs_that_copy_its_name(self, enqueued, django_capture_on_commit_callbacks):
        from apps.annotations.tests.factories import GraphFactory
        from apps.scribes.tests.factories import HandFactory

        hand = HandFactory()
        graph = GraphFactory(hand=hand)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            hand.name = "Main Hand (revised)"
            hand.save(update_fields=["name"])

        assert ("hands", [hand.pk]) in enqueued
        assert ("graphs", [graph.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_renaming_a_scribe_syncs_graphs_through_its_hands(self, enqueued, django_capture_on_commit_callbacks):
        from apps.annotations.tests.factories import GraphFactory
        from apps.scribes.tests.factories import HandFactory, ScribeFactory

        scribe = ScribeFactory()
        graph = GraphFactory(hand=HandFactory(scribe=scribe))
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            scribe.name = "William of Kelso"
            scribe.save(update_fields=["name"])

        assert ("scribes", [scribe.pk]) in enqueued
        assert ("graphs", [graph.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_editing_a_manuscript_syncs_everything_under_it(self, enqueued, django_capture_on_commit_callbacks):
        from apps.annotations.tests.factories import GraphFactory
        from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory, ItemPartFactory
        from apps.scribes.tests.factories import HandFactory

        part = ItemPartFactory()
        image = ItemImageFactory(item_part=part)
        hand = HandFactory(item_part=part)
        graph = GraphFactory(item_image=image)
        text = ImageTextFactory(item_image=image)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            part.custom_label = "Part A"
            part.save(update_fields=["custom_label"])

        assert ("item-parts", [part.pk]) in enqueued
        assert ("item-images", [image.pk]) in enqueued
        assert ("hands", [hand.pk]) in enqueued
        assert ("graphs", [graph.pk]) in enqueued
        assert ("texts", [text.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_publishing_a_text_syncs_it(self, enqueued, django_capture_on_commit_callbacks):
        """The case the whole feature is for: Draft to Live must reach search
        without a reindex."""
        from apps.manuscripts.models import ImageText
        from apps.manuscripts.tests.factories import ImageTextFactory

        text = ImageTextFactory(status=ImageText.Status.DRAFT)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            text.status = ImageText.Status.LIVE
            text.save(update_fields=["status"])

        assert ("texts", [text.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_deleting_an_image_syncs_its_own_id_and_its_manuscript(self, enqueued, django_capture_on_commit_callbacks):
        """Django clears an instance's pk once a delete finishes, so the
        resolvers must capture it while the receiver runs."""
        from apps.manuscripts.tests.factories import ItemImageFactory

        image = ItemImageFactory()
        image_pk, part_pk = image.pk, image.item_part_id
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            image.delete()

        assert ("item-images", [image_pk]) in enqueued
        assert ("item-parts", [part_pk]) in enqueued


@pytest.mark.django_db
class TestPublicStatusTransitions:
    """A text moving in or out of the public statuses must move its documents
    with it. The registry keeps non-public rows out of the index, so before
    incremental sync this only took effect on the next full reindex.
    """

    def test_a_draft_text_is_removed_from_the_texts_index(self):
        from apps.manuscripts.models import ImageText
        from apps.manuscripts.tests.factories import ImageTextFactory

        text = ImageTextFactory(status=ImageText.Status.DRAFT)
        fake_writer = MagicMock()

        IndexingService(writer=fake_writer).update_documents_by_ids(IndexType.TEXTS, [text.pk])

        fake_writer.update_documents.assert_not_called()
        fake_writer.delete_documents.assert_called_once_with(IndexType.TEXTS, [text.pk])

    def test_a_draft_text_has_its_derived_documents_cleared_by_filter(self):
        from apps.manuscripts.models import ImageText
        from apps.manuscripts.tests.factories import ImageTextFactory

        text = ImageTextFactory(status=ImageText.Status.DRAFT)
        fake_writer = MagicMock()

        IndexingService(writer=fake_writer).update_documents_by_ids(IndexType.CLAUSES, [text.pk])

        fake_writer.delete_documents_by_filter.assert_called_once_with(IndexType.CLAUSES, f"image_text IN [{text.pk}]")
        fake_writer.update_documents.assert_not_called()

    def test_a_published_text_is_indexed(self):
        from apps.manuscripts.models import ImageText
        from apps.manuscripts.tests.factories import ImageTextFactory

        text = ImageTextFactory(status=ImageText.Status.LIVE, content="<p>Willelmus rex</p>")
        fake_writer = MagicMock()

        IndexingService(writer=fake_writer).update_documents_by_ids(IndexType.TEXTS, [text.pk])

        fake_writer.delete_documents.assert_not_called()
        (index_type, docs), _ = fake_writer.update_documents.call_args
        assert index_type == IndexType.TEXTS
        assert docs[0]["id"] == text.pk


@pytest.mark.django_db
class TestSentinelRows:
    """The DigiPal import left an ItemPart at pk=-1, which the registration
    filters out of the index. Syncing it must be a no-op, not an error."""

    def test_syncing_the_sentinel_item_part_removes_it_rather_than_failing(self):
        fake_writer = MagicMock()

        IndexingService(writer=fake_writer).update_documents_by_ids(IndexType.ITEM_PARTS, [-1])

        fake_writer.update_documents.assert_not_called()
        fake_writer.delete_documents.assert_called_once_with(IndexType.ITEM_PARTS, [-1])


@pytest.mark.django_db
class TestManuscriptSpineSync:
    """The models a manuscript's identity hangs off — its description, the item
    holding it, that item's repository, its date. Each is edited on its own
    backoffice page and each is copied into documents across several indexes.
    """

    @pytest.fixture
    def manuscript(self):
        """One manuscript with an image, a hand, an annotation and a text."""
        from apps.annotations.tests.factories import GraphFactory
        from apps.manuscripts.tests.factories import (
            CurrentItemFactory,
            HistoricalItemFactory,
            ImageTextFactory,
            ItemImageFactory,
            ItemPartFactory,
        )
        from apps.scribes.tests.factories import HandFactory

        current_item = CurrentItemFactory()
        historical_item = HistoricalItemFactory()
        part = ItemPartFactory(current_item=current_item, historical_item=historical_item)
        image = ItemImageFactory(item_part=part)
        return SimpleNamespace(
            current_item=current_item,
            repository=current_item.repository,
            historical_item=historical_item,
            date=historical_item.date,
            part=part,
            image=image,
            hand=HandFactory(item_part=part),
            graph=GraphFactory(item_image=image),
            text=ImageTextFactory(item_image=image),
        )

    def _assert_reaches_manuscript_documents(self, enqueued, ms):
        assert ("item-parts", [ms.part.pk]) in enqueued
        assert ("item-images", [ms.image.pk]) in enqueued
        assert ("graphs", [ms.graph.pk]) in enqueued
        assert ("texts", [ms.text.pk]) in enqueued

    def _assert_reaches_everything(self, enqueued, ms):
        self._assert_reaches_manuscript_documents(enqueued, ms)
        assert ("hands", [ms.hand.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_changing_the_manuscript_type_reaches_every_index(
        self, manuscript, enqueued, django_capture_on_commit_callbacks
    ):
        enqueued.clear()
        with django_capture_on_commit_callbacks(execute=True):
            manuscript.historical_item.type = "letter"
            manuscript.historical_item.save(update_fields=["type"])

        self._assert_reaches_everything(enqueued, manuscript)

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_changing_a_shelfmark_reaches_every_index(self, manuscript, enqueued, django_capture_on_commit_callbacks):
        enqueued.clear()
        with django_capture_on_commit_callbacks(execute=True):
            manuscript.current_item.shelfmark = "Add. Ch. 9999"
            manuscript.current_item.save(update_fields=["shelfmark"])

        self._assert_reaches_everything(enqueued, manuscript)

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_renaming_a_repository_reaches_every_index(self, manuscript, enqueued, django_capture_on_commit_callbacks):
        """`repository_name` and `repository_city` are facets on eight of the
        nine tabs, so a rename that only reached the Manuscripts tab would leave
        seven filter sidebars offering a name that no longer exists."""
        enqueued.clear()
        with django_capture_on_commit_callbacks(execute=True):
            manuscript.repository.name = "British Library (renamed)"
            manuscript.repository.save(update_fields=["name"])

        self._assert_reaches_everything(enqueued, manuscript)

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_correcting_a_date_reaches_every_index(self, manuscript, enqueued, django_capture_on_commit_callbacks):
        """Documents copy the date string *and* its numeric weights, which drive
        the date-range facet — so a stale weight returns wrong results rather
        than merely showing stale text."""
        enqueued.clear()
        with django_capture_on_commit_callbacks(execute=True):
            manuscript.date.date = "1235 X 1242"
            manuscript.date.min_weight = 1235
            manuscript.date.save(update_fields=["date", "min_weight"])

        self._assert_reaches_manuscript_documents(enqueued, manuscript)
        # Not hands: a hand document carries its own date, not its manuscript's.
        assert ("hands", [manuscript.hand.pk]) not in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_a_hand_is_synced_through_its_own_date_not_its_manuscripts(
        self, manuscript, enqueued, django_capture_on_commit_callbacks
    ):
        from apps.common.tests.factories import DateFactory

        own_date = DateFactory(date="1300")
        manuscript.hand.date = own_date
        manuscript.hand.save(update_fields=["date"])
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            own_date.date = "1301"
            own_date.save(update_fields=["date"])

        assert ("hands", [manuscript.hand.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_deleting_a_date_still_syncs_the_manuscripts_that_referenced_it(
        self, manuscript, enqueued, django_capture_on_commit_callbacks
    ):
        """`HistoricalItem.date` is SET_NULL, and Django runs that update between
        the two delete signals, so resolving later than `pre_delete` finds nothing.
        """
        enqueued.clear()
        with django_capture_on_commit_callbacks(execute=True):
            manuscript.date.delete()

        self._assert_reaches_manuscript_documents(enqueued, manuscript)


@pytest.mark.django_db(transaction=True)
class TestTagWriteOrdering:
    """DRF writes `tags` after `save()` and `on_commit` fires immediately, so a
    sync can be queued before the tag rows land.

    `transaction=True` is required: under the usual test transaction `on_commit`
    never runs, which would hide it.
    """

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_tags_are_visible_when_the_sync_is_queued(self, management_client, monkeypatch):
        from apps.manuscripts.models import ItemImage
        from apps.manuscripts.tests.factories import ItemImageFactory

        image = ItemImageFactory()
        seen: list[tuple[str, list[str]]] = []

        def record(segment, pks):
            tags = sorted(tag.name for tag in ItemImage.objects.get(pk=image.pk).tags.all())
            seen.append((segment, tags))

        monkeypatch.setattr("apps.search.signals.sync_search_documents.delay", record)

        response = management_client.patch(
            f"/api/v1/manuscripts/management/item-images/{image.pk}/",
            {"tags": ["damaged"]},
            format="json",
        )
        assert response.status_code == 200

        queued = [tags for segment, tags in seen if segment == "item-images"]
        assert queued, "no item-images sync was queued for the tag write"
        assert any("damaged" in tags for tags in queued), f"every queued sync ran before the tag rows landed: {queued}"


@pytest.mark.django_db
class TestTaxonomySync:
    """The palaeographic and bibliographic vocabularies. Their names are facets
    on the Graphs, Images and Manuscripts tabs, so a rename that did not reach
    the index leaves a filter offering a value that no longer exists.
    """

    @pytest.fixture
    def annotated(self):
        from apps.annotations.tests.factories import GraphComponentFactory, GraphFactory
        from apps.manuscripts.tests.factories import ItemImageFactory
        from apps.symbols_structure.tests.factories import (
            AllographFactory,
            ComponentFactory,
            FeatureFactory,
            PositionFactory,
        )

        image = ItemImageFactory()
        allograph = AllographFactory()
        graph = GraphFactory(item_image=image, allograph=allograph)
        component = ComponentFactory()
        feature = FeatureFactory()
        graph_component = GraphComponentFactory(graph=graph, component=component)
        graph_component.features.add(feature)
        position = PositionFactory()
        graph.positions.add(position)
        return SimpleNamespace(
            image=image,
            graph=graph,
            allograph=allograph,
            character=allograph.character,
            component=component,
            feature=feature,
            position=position,
        )

    def _assert_reaches_annotations(self, enqueued, a):
        assert ("graphs", [a.graph.pk]) in enqueued
        assert ("item-images", [a.image.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    @pytest.mark.parametrize("target", ["allograph", "character", "component", "feature", "position"])
    def test_renaming_a_symbol_reaches_its_annotations(
        self, annotated, enqueued, django_capture_on_commit_callbacks, target
    ):
        row = getattr(annotated, target)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            row.name = f"{target}-renamed"
            row.save(update_fields=["name"])

        self._assert_reaches_annotations(enqueued, annotated)

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_editing_a_catalogue_number_reaches_the_documents_that_print_it(
        self, enqueued, django_capture_on_commit_callbacks
    ):
        from apps.manuscripts.tests.factories import (
            CatalogueNumberFactory,
            HistoricalItemFactory,
            ImageTextFactory,
            ItemImageFactory,
            ItemPartFactory,
        )
        from apps.scribes.tests.factories import HandFactory

        historical_item = HistoricalItemFactory()
        catalogue_number = CatalogueNumberFactory(historical_item=historical_item)
        part = ItemPartFactory(historical_item=historical_item)
        hand = HandFactory(item_part=part)
        text = ImageTextFactory(item_image=ItemImageFactory(item_part=part))
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            catalogue_number.number = "Ker 236"
            catalogue_number.save(update_fields=["number"])

        assert ("item-parts", [part.pk]) in enqueued
        assert ("hands", [hand.pk]) in enqueued
        assert ("texts", [text.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_renaming_a_bibliographic_source_reaches_the_same_documents(
        self, enqueued, django_capture_on_commit_callbacks
    ):
        """`str(CatalogueNumber)` is `"{catalogue.label} {number}"`, so the
        source's label is printed in every document showing a catalogue number.
        """
        from apps.manuscripts.tests.factories import CatalogueNumberFactory, HistoricalItemFactory, ItemPartFactory

        historical_item = HistoricalItemFactory()
        catalogue_number = CatalogueNumberFactory(historical_item=historical_item)
        part = ItemPartFactory(historical_item=historical_item)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            catalogue_number.catalogue.label = "Ker"
            catalogue_number.catalogue.save(update_fields=["label"])

        assert ("item-parts", [part.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_renaming_a_format_reaches_the_manuscripts_using_it(self, enqueued, django_capture_on_commit_callbacks):
        from apps.manuscripts.tests.factories import HistoricalItemFactory, ItemPartFactory

        historical_item = HistoricalItemFactory()
        part = ItemPartFactory(historical_item=historical_item)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            historical_item.format.name = "codex"
            historical_item.format.save(update_fields=["name"])

        assert ("item-parts", [part.pk]) in enqueued


@pytest.mark.django_db
class TestFurtherDenormalizations:
    """Values documents copy from places the model graph does not make obvious."""

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_a_scribe_is_synced_through_its_period(self, enqueued, django_capture_on_commit_callbacks):
        """`Scribe.period` is a Date as well, and the scribe document prints it."""
        from apps.scribes.tests.factories import ScribeFactory

        scribe = ScribeFactory()
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            scribe.period.date = "1200 X 1250"
            scribe.period.save(update_fields=["date"])

        assert ("scribes", [scribe.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_redrawing_a_text_region_rebuilds_the_text_documents(self, enqueued, django_capture_on_commit_callbacks):
        """Text-derived documents bake a TEXT graph's polygon in as
        `annotation_coordinates`, which is what crops a clause card's thumbnail.
        """
        from apps.annotations.tests.factories import GraphFactory
        from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory

        image = ItemImageFactory()
        text = ImageTextFactory(item_image=image)
        graph = GraphFactory(item_image=image, annotation_type=Graph.AnnotationType.TEXT)
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            graph.annotation = {"type": "Polygon", "coordinates": [[[1, 2], [3, 4]]]}
            graph.save(update_fields=["annotation"])

        assert ("texts", [text.pk]) in enqueued
        assert ("clauses", [text.pk]) in enqueued

    @override_settings(SEARCH_AUTO_REINDEX=True)
    def test_a_fixture_load_does_not_queue_a_sync(self, enqueued, django_capture_on_commit_callbacks):
        """`loaddata` sends post_save with `raw=True` while related rows may not
        exist yet, and a restore is followed by a reindex anyway.
        """
        from django.db.models.signals import post_save

        from apps.manuscripts.models import ItemImage
        from apps.manuscripts.tests.factories import ItemImageFactory

        image = ItemImageFactory()
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            post_save.send(sender=ItemImage, instance=image, created=False, raw=True)
        assert enqueued == []

        with django_capture_on_commit_callbacks(execute=True):
            post_save.send(sender=ItemImage, instance=image, created=False, raw=False)
        assert enqueued, "a non-raw save should still queue a sync"
