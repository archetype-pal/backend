"""vision 0002 stamps the vectors made before it with the crop their glyph has now."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import pytest

from apps.vision.models import GlyphEmbedding

BEFORE = [("vision", "0001_initial")]
AFTER = [("vision", "0002_glyphembedding_crop_digest")]

RING = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[10, 70], [40, 70], [40, 90], [10, 90]]]}}


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def back_to_latest():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("back_to_latest")
def test_each_vector_is_stamped_with_its_glyph_s_present_crop():
    old = _migrate(BEFORE)
    HistoricalItem = old.get_model("manuscripts", "HistoricalItem")
    ItemPart = old.get_model("manuscripts", "ItemPart")
    ItemImage = old.get_model("manuscripts", "ItemImage")
    Graph = old.get_model("annotations", "Graph")
    OldEmbedding = old.get_model("vision", "GlyphEmbedding")
    part = ItemPart.objects.create(historical_item=HistoricalItem.objects.create(type="Charter"))
    pages = [ItemImage.objects.create(item_part=part, image=f"historical_items/{name}.jp2") for name in ("a", "b")]
    graphs = [
        Graph.objects.create(item_image=pages[0], annotation=RING, annotation_type="editorial"),
        Graph.objects.create(item_image=pages[1], annotation={"test": "test"}, annotation_type="editorial"),
    ]
    for graph in graphs:
        for encoder in ("trocr", "ink"):
            OldEmbedding.objects.create(
                graph=graph, encoder=encoder, model_name="m", model_version="v", dimensions=1, vector=b"\0" * 4
            )

    new = _migrate(AFTER)

    stamped = new.get_model("vision", "GlyphEmbedding").objects.values_list("graph_id", "crop_digest")
    expected = {
        graphs[0].pk: GlyphEmbedding.crop_digest_of("historical_items/a.jp2", RING),
        graphs[1].pk: GlyphEmbedding.crop_digest_of("historical_items/b.jp2", {"test": "test"}),
    }
    assert sorted(stamped) == sorted((graph_id, expected[graph_id]) for graph_id in expected for _ in range(2))
    assert len(set(expected.values())) == 2
