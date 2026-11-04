"""The vector a glyph is searched by (W1.2): the harness's fusion, written down.

The parts are swapped for small ones where the arithmetic is the point, so
each vector can be written out; the real parts are checked for their size.
"""

import math

import numpy as np
import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.vision.models import GlyphEmbedding
from apps.vision.services import glyph_search
from apps.vision.services.evaluation import fuse, load_vectors
from apps.vision.services.glyph_search import Part, search_vector

pytestmark = pytest.mark.django_db

SMALL = (Part("trocr", "rev-1", 2, weight=3.0), Part("ink", "otsu-1", 3))
REDRAWN = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [9, 0], [9, 9], [0, 9]]]}}


@pytest.fixture
def small_parts(monkeypatch):
    monkeypatch.setattr(glyph_search, "PARTS", SMALL)
    monkeypatch.setattr(glyph_search, "ENCODERS", tuple(part.encoder for part in SMALL))


def _embed(graph: Graph, encoder: str, vector: list[float], *, version: str | None = None) -> None:
    """Store a vector as an embedding pass would, made from the crop the glyph has now."""
    part = next(part for part in glyph_search.PARTS if part.encoder == encoder)
    GlyphEmbedding.objects.update_or_create(
        graph=graph,
        encoder=encoder,
        defaults={
            "model_name": encoder,
            "model_version": version or part.model_version,
            "dimensions": len(vector),
            "vector": GlyphEmbedding.pack(vector),
            "crop_digest": GlyphEmbedding.crop_digest_for(graph),
        },
    )


def _glyph(trocr: list[float], ink: list[float]) -> Graph:
    graph = GraphFactory()
    _embed(graph, "trocr", trocr)
    _embed(graph, "ink", ink)
    return graph


def _cosine(a: list[float], b: list[float]) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


@pytest.mark.usefixtures("small_parts")
class TestSearchVector:
    def test_is_the_harness_s_fusion_of_the_same_vectors(self):
        rng = np.random.default_rng(7)
        graphs = [_glyph(list(rng.normal(size=2)), list(rng.normal(size=3))) for _ in range(4)]

        fused = fuse([load_vectors("trocr"), load_vectors("ink")], {"trocr": 3.0})

        for graph in graphs:
            vector = search_vector(graph)
            assert vector is not None
            np.testing.assert_allclose(vector, fused.matrix[fused.index[graph.pk]], atol=1e-6)

    def test_a_dot_product_is_the_weighted_mean_of_the_parts_cosines(self):
        a = _glyph([1.0, 0.0], [0.0, 2.0, 0.0])
        b = _glyph([3.0, 4.0], [0.0, 1.0, 1.0])

        similarity = float(np.dot(search_vector(a), search_vector(b)))

        expected = (3 * _cosine([1, 0], [3, 4]) + 1 * _cosine([0, 2, 0], [0, 1, 1])) / 4
        assert similarity == pytest.approx(expected, abs=1e-5)

    def test_is_unit_length(self):
        vector = search_vector(_glyph([3.0, 4.0], [1.0, 2.0, 2.0]))

        assert math.fsum(value * value for value in vector) == pytest.approx(1.0, abs=1e-5)

    def test_a_glyph_missing_a_part_has_none(self):
        graph = GraphFactory()
        _embed(graph, "trocr", [1.0, 0.0])

        assert search_vector(graph) is None

    def test_a_part_from_other_weights_gives_none(self):
        graph = GraphFactory()
        _embed(graph, "trocr", [1.0, 0.0], version="rev-2")
        _embed(graph, "ink", [1.0, 0.0, 0.0])

        assert search_vector(graph) is None

    def test_a_part_of_another_size_gives_none(self):
        graph = GraphFactory()
        _embed(graph, "trocr", [1.0, 0.0, 0.0])
        _embed(graph, "ink", [1.0, 0.0, 0.0])

        assert search_vector(graph) is None

    def test_a_redrawn_glyph_has_none_until_every_part_is_embedded_again(self):
        graph = _glyph([1.0, 0.0], [0.0, 1.0, 0.0])
        graph.annotation = REDRAWN
        graph.save()

        assert search_vector(graph) is None

        _embed(graph, "trocr", [1.0, 0.0])
        assert search_vector(graph) is None

        _embed(graph, "ink", [0.0, 1.0, 0.0])
        assert search_vector(graph) is not None

    def test_a_glyph_whose_page_has_another_image_has_none(self):
        graph = _glyph([1.0, 0.0], [0.0, 1.0, 0.0])
        graph.item_image.image = "historical_items/rescanned.jp2"
        graph.item_image.save()

        assert search_vector(Graph.objects.select_related("item_image").get(pk=graph.pk)) is None

    def test_a_blank_part_adds_nothing_but_leaves_the_rest(self):
        vector = search_vector(_glyph([0.0, 2.0], [0.0, 0.0, 0.0]))

        assert vector == pytest.approx([0.0, math.sqrt(3 / 4), 0.0, 0.0, 0.0], abs=1e-6)

    def test_a_glyph_blank_in_every_part_has_none(self):
        assert search_vector(_glyph([0.0, 0.0], [0.0, 0.0, 0.0])) is None

    def test_ignores_vectors_from_encoders_not_in_the_parts(self):
        graph = _glyph([1.0, 0.0], [0.0, 1.0, 0.0])
        GlyphEmbedding.objects.create(
            graph=graph, encoder="pixels", model_name="raw-pixels", model_version="1", dimensions=1, vector=b"\0" * 4
        )

        assert len(search_vector(graph)) == 5

    def test_prefetched_graphs_need_no_further_query(self, django_assert_num_queries):
        for _ in range(3):
            _glyph([1.0, 0.0], [0.0, 1.0, 0.0])
        graphs = list(Graph.objects.select_related("item_image").prefetch_related(glyph_search.prefetch()))

        with django_assert_num_queries(0):
            vectors = [search_vector(graph) for graph in graphs]

        assert all(vector is not None for vector in vectors)


def test_the_parts_make_a_vector_of_the_declared_size():
    graph = GraphFactory()
    for part in glyph_search.PARTS:
        _embed(graph, part.encoder, [1.0] * part.dimensions)

    vector = search_vector(graph)

    assert vector is not None
    assert len(vector) == glyph_search.DIMENSIONS == sum(part.dimensions for part in glyph_search.PARTS)
