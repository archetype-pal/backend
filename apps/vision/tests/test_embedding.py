"""Glyph vectors from a self-hosted encoder (W1.2).

The encoder and the image server are mocked: the encoder is checked against its
weights when its image is built, and the crop's geometry against the image
server's conventions in `test_images`. What is pinned here is what a pass
stores, what it skips, and what it refuses.
"""

import base64
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.ml.models import MLJob
from apps.ml.providers import InferenceResult, ProviderError
from apps.vision import images
from apps.vision.models import GlyphEmbedding
from apps.vision.services import embedding, glyph_search

pytestmark = pytest.mark.django_db

RING = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[10, 70], [40, 70], [40, 90], [10, 90]]]}}


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_DAILY_COST_CAP_MICROS = 0
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    settings.ML_EMBEDDER_URL = "http://embedder:8080"
    return settings


def _vector(graph_id: int) -> list[float]:
    """A stand-in vector that says which glyph it was made for."""
    return [float(graph_id), 0.5, -1.0]


class _Encoder:
    """Answers each crop with `_vector` of the glyph the crop was made from."""

    def __init__(self, *, fail_batches: tuple[int, ...] = ()) -> None:
        self.batches: list[list[str]] = []
        self.fail_batches = fail_batches

    def run(self, request):
        self.batches.append(list(request.inputs["images"]))
        if len(self.batches) in self.fail_batches:
            raise ProviderError("The encoder could not be reached.")
        vectors = [_vector(int(base64.b64decode(image))) for image in request.inputs["images"]]
        return InferenceResult(
            output={"vectors": vectors, "dimensions": 3},
            model_name="LaMOP/TrOCR_Manicule_2026_Latin_Medieval",
            model_version="08e146d2",
        )


@pytest.fixture
def encoder():
    fake = _Encoder()
    with mock.patch("apps.ml.providers.embedder.EmbedderProvider.run", side_effect=fake.run):
        yield fake


@pytest.fixture
def crops():
    """Every page measures; each crop is the glyph's id, so a vector can be traced to it."""
    with (
        mock.patch.object(images, "dimensions", return_value=(100, 100)),
        mock.patch.object(
            embedding, "crop", side_effect=lambda graph: base64.b64encode(str(graph.pk).encode()).decode()
        ),
    ):
        yield


def _stored(encoder: str = "trocr") -> dict[int, list[float]]:
    return {row.graph_id: row.values for row in GlyphEmbedding.objects.filter(encoder=encoder)}


def _embedded(graph: Graph, encoder: str = "trocr") -> None:
    """A vector made from the crop the glyph has now, as a pass would store it."""
    GlyphEmbedding.objects.create(
        graph=graph,
        encoder=encoder,
        model_name="m",
        model_version="v",
        dimensions=1,
        vector=GlyphEmbedding.pack([1.0]),
        crop_digest=GlyphEmbedding.crop_digest_for(graph),
    )


class TestStorage:
    def test_a_vector_round_trips_as_float32(self):
        graph = GraphFactory()
        row = GlyphEmbedding.objects.create(
            graph=graph,
            encoder="trocr",
            model_name="m",
            model_version="v",
            dimensions=3,
            vector=GlyphEmbedding.pack([0.25, -1.5, 3.0]),
        )

        assert len(bytes(row.vector)) == 12
        assert GlyphEmbedding.objects.get(pk=row.pk).values == [0.25, -1.5, 3.0]

    def test_the_database_refuses_a_vector_that_does_not_fit_its_length(self):
        graph = GraphFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            GlyphEmbedding.objects.create(
                graph=graph,
                encoder="trocr",
                model_name="m",
                model_version="v",
                dimensions=4,
                vector=GlyphEmbedding.pack([1.0, 2.0, 3.0]),
            )

    def test_a_glyph_has_one_vector_per_encoder(self):
        graph = GraphFactory()
        fields = {"model_name": "m", "model_version": "v", "dimensions": 1, "vector": GlyphEmbedding.pack([1.0])}
        GlyphEmbedding.objects.create(graph=graph, encoder="trocr", **fields)
        GlyphEmbedding.objects.create(graph=graph, encoder="pixels", **fields)

        with pytest.raises(IntegrityError), transaction.atomic():
            GlyphEmbedding.objects.create(graph=graph, encoder="trocr", **fields)


class TestSelection:
    def test_glyphs_only_and_not_those_already_embedded_by_this_encoder(self):
        fresh = GraphFactory()
        done = GraphFactory()
        other_encoder = GraphFactory()
        GraphFactory(annotation_type=Graph.AnnotationType.TEXT, allograph=None, hand=None)
        trashed = GraphFactory()
        trashed.soft_delete()
        _embedded(done)
        _embedded(other_encoder, encoder="pixels")

        assert list(embedding.glyphs_to_embed("trocr")) == [fresh, other_encoder]
        assert list(embedding.glyphs_to_embed("trocr", force=True)) == [fresh, done, other_encoder]

    def test_a_glyph_redrawn_or_given_another_page_image_is_embedded_again(self):
        current, redrawn, rescanned = GraphFactory.create_batch(3)
        for graph in (current, redrawn, rescanned):
            _embedded(graph)
            _embedded(graph, encoder="ink")
        redrawn.annotation = RING
        redrawn.save()
        rescanned.item_image.image = "historical_items/rescanned.jp2"
        rescanned.item_image.save()

        assert sorted(embedding.stale_glyphs("trocr")) == [redrawn.pk, rescanned.pk]
        assert list(embedding.glyphs_to_embed("trocr")) == [redrawn, rescanned]

    def test_a_vector_with_no_record_of_its_crop_is_stale(self):
        graph = GraphFactory()
        GlyphEmbedding.objects.create(
            graph=graph, encoder="trocr", model_name="m", model_version="v", dimensions=1, vector=b"\0" * 4
        )

        assert list(embedding.glyphs_to_embed("trocr")) == [graph]


class TestCrop:
    def test_asks_the_image_server_for_the_glyph_at_most_224_a_side(self, settings):
        settings.IIIF_HOST = "http://localhost:8182"
        settings.IIIF_INTERNAL_HOST = "http://image_server:1024"
        graph = GraphFactory(annotation=RING)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"\x89PNG-bytes"

        with (
            mock.patch.object(images, "dimensions", return_value=(100, 100)),
            mock.patch("apps.vision.services.embedding.urllib.request.urlopen", return_value=response) as urlopen,
        ):
            encoded = embedding.crop(graph)

        # The stored ring is Y-up: 70..90 from the bottom of a 100-high page is 10..30 from the top.
        url = urlopen.call_args.args[0]
        assert url == f"{images.internal_identifier(graph.item_image)}/10,10,30,20/%5E!224,224/0/default.png"
        assert url.startswith("http://image_server:1024/")
        assert base64.b64decode(encoded) == b"\x89PNG-bytes"

    @pytest.mark.parametrize(
        ("annotation", "fetched", "message"),
        [
            ({"type": "Feature"}, b"png", "no region"),
            (RING, OSError("refused"), "Could not fetch the crop"),
            (RING, b"", "empty or too large"),
            (RING, b"x" * (embedding.MAX_CROP_BYTES + 1), "empty or too large"),
        ],
    )
    def test_a_crop_it_cannot_get_is_unavailable(self, annotation, fetched, message):
        graph = GraphFactory(annotation=annotation)
        response = mock.MagicMock()
        if isinstance(fetched, bytes):
            response.__enter__.return_value.read.return_value = fetched
        urlopen = mock.Mock(side_effect=fetched) if isinstance(fetched, Exception) else mock.Mock(return_value=response)

        with (
            mock.patch.object(images, "dimensions", return_value=(100, 100)),
            mock.patch("apps.vision.services.embedding.urllib.request.urlopen", urlopen),
            pytest.raises(images.ImageUnavailable, match=message),
        ):
            embedding.crop(graph)


class TestPass:
    def test_stores_each_glyph_s_own_vector_with_the_job_that_made_it(self, enabled, encoder, crops):
        graphs = GraphFactory.create_batch(5)

        tally = embedding.embed_glyphs(Graph.objects.order_by("pk"), batch_size=2)

        assert tally.as_dict() == {"embedded": 5, "unavailable": 0, "failed": 0, "jobs": 3}
        assert _stored() == {graph.pk: _vector(graph.pk) for graph in graphs}
        jobs = MLJob.objects.filter(provider="trocr").order_by("pk")
        assert [job.params["graph_ids"] for job in jobs] == [
            [graphs[0].pk, graphs[1].pk],
            [graphs[2].pk, graphs[3].pk],
            [graphs[4].pk],
        ]
        row = GlyphEmbedding.objects.get(graph=graphs[2])
        assert (row.model_name, row.model_version, row.dimensions, row.ml_job) == (
            "LaMOP/TrOCR_Manicule_2026_Latin_Medieval",
            "08e146d2",
            3,
            jobs[1],
        )

    def test_stamps_each_vector_with_the_crop_it_was_cut_from(self, enabled, encoder, crops):
        GraphFactory.create_batch(3)

        embedding.embed_glyphs(Graph.objects.order_by("pk"), batch_size=2)

        rows = GlyphEmbedding.objects.select_related("graph__item_image")
        assert len(rows) == 3
        assert all(row.crop_digest == GlyphEmbedding.crop_digest_for(row.graph) for row in rows)
        assert embedding.stale_glyphs("trocr") == []

    def test_a_glyph_redrawn_while_it_was_cropped_is_stale_at_once(self, enabled, encoder, crops):
        graph = GraphFactory()
        as_cropped = Graph.objects.select_related("item_image").get(pk=graph.pk)
        Graph.objects.filter(pk=graph.pk).update(annotation=RING)

        embedding.embed_glyphs([as_cropped])

        assert embedding.stale_glyphs("trocr") == [graph.pk]

    def test_skips_the_glyphs_of_a_page_the_image_server_cannot_serve_asking_once(self, enabled, encoder):
        missing_page = ItemImageFactory()
        on_missing = GraphFactory.create_batch(3, item_image=missing_page)
        served = GraphFactory()

        def measure(image):
            if image.pk == missing_page.pk:
                raise images.ImageUnavailable("404")
            return (100, 100)

        with (
            mock.patch.object(images, "dimensions", side_effect=measure) as dimensions,
            mock.patch.object(embedding, "crop", side_effect=lambda g: base64.b64encode(str(g.pk).encode()).decode()),
        ):
            tally = embedding.embed_glyphs(Graph.objects.order_by("pk"), batch_size=1)

        assert (tally.embedded, tally.unavailable) == (1, 3)
        assert _stored() == {served.pk: _vector(served.pk)}
        missing_lookups = [call for call in dimensions.call_args_list if call.args[0].pk == missing_page.pk]
        assert len(missing_lookups) == 1
        assert not GlyphEmbedding.objects.filter(graph__in=on_missing).exists()

    def test_a_failed_batch_is_counted_and_the_next_one_still_runs(self, enabled, crops):
        graphs = GraphFactory.create_batch(4)
        fake = _Encoder(fail_batches=(1,))

        with mock.patch("apps.ml.providers.embedder.EmbedderProvider.run", side_effect=fake.run):
            tally = embedding.embed_glyphs(Graph.objects.order_by("pk"), batch_size=2)

        assert (tally.embedded, tally.failed, len(tally.jobs)) == (2, 2, 2)
        assert set(_stored()) == {graphs[2].pk, graphs[3].pk}

    def test_stops_at_the_first_refusal(self, settings, encoder, crops):
        settings.ML_INFERENCE_ENABLED = False
        GraphFactory.create_batch(4)

        tally = embedding.embed_glyphs(Graph.objects.order_by("pk"), batch_size=2)

        assert "ML_INFERENCE_ENABLED" in tally.refused
        assert MLJob.objects.filter(status=MLJob.Status.REFUSED).count() == 1
        assert encoder.batches == []
        assert not GlyphEmbedding.objects.exists()

    def test_re_embedding_replaces_the_old_vector(self, enabled, encoder, crops):
        graph = GraphFactory()
        GlyphEmbedding.objects.create(
            graph=graph,
            encoder="trocr",
            model_name="old",
            model_version="0",
            dimensions=1,
            vector=GlyphEmbedding.pack([9.0]),
        )

        embedding.embed_glyphs(embedding.glyphs_to_embed(force=True))

        row = GlyphEmbedding.objects.get(graph=graph, encoder="trocr")
        assert (row.model_version, row.values) == ("08e146d2", _vector(graph.pk))

    def test_announces_the_glyphs_whose_search_vector_changed(self, enabled, encoder, crops):
        graphs = GraphFactory.create_batch(3)
        received: list[list[int]] = []

        def receive(sender, graph_ids, **kwargs):
            received.append(graph_ids)

        glyph_search.search_vectors_changed.connect(receive, weak=False)
        try:
            embedding.embed_glyphs(Graph.objects.order_by("pk"), batch_size=2)
        finally:
            glyph_search.search_vectors_changed.disconnect(receive)

        assert received == [[graphs[0].pk, graphs[1].pk], [graphs[2].pk]]

    def test_says_nothing_for_an_encoder_the_search_vector_does_not_use(self, enabled, encoder, crops, monkeypatch):
        GraphFactory()
        monkeypatch.setattr(embedding, "SEARCH_ENCODERS", ("ink", "hog"))

        with mock.patch.object(glyph_search.search_vectors_changed, "send") as send:
            embedding.embed_glyphs(Graph.objects.all())

        send.assert_not_called()

    def test_a_hosted_encoder_is_refused_before_a_crop_is_fetched(self, enabled):
        GraphFactory()

        with (
            mock.patch.object(embedding, "crop") as crop,
            pytest.raises(embedding.EncoderNotAllowed, match="self-hosted"),
        ):
            embedding.embed_glyphs(Graph.objects.all(), encoder="openrouter")
        crop.assert_not_called()


class TestCommand:
    def test_embeds_and_reports(self, enabled, encoder, crops):
        GraphFactory.create_batch(3)
        out = StringIO()

        call_command("embed_glyphs", "--batch-size", "2", stdout=out)

        assert "3 glyphs to embed with trocr." in out.getvalue()
        assert "Done: embedded 3, unavailable 0, failed 0, jobs 2." in out.getvalue()
        assert GlyphEmbedding.objects.count() == 3

    def test_a_limit_embeds_only_that_many(self, enabled, encoder, crops):
        GraphFactory.create_batch(3)

        call_command("embed_glyphs", "--limit", "2", stdout=StringIO())

        assert GlyphEmbedding.objects.count() == 2

    def test_says_why_it_was_refused(self, settings, encoder, crops):
        settings.ML_INFERENCE_ENABLED = False
        GraphFactory()

        with pytest.raises(CommandError, match="ML_INFERENCE_ENABLED"):
            call_command("embed_glyphs", stdout=StringIO())

    @pytest.mark.parametrize("size", ["0", "65"])
    def test_a_batch_must_fit_one_encoder_request(self, size):
        with pytest.raises(CommandError, match="between 1 and 64"):
            call_command("embed_glyphs", "--batch-size", size, stdout=StringIO())

    def test_a_hosted_encoder_is_refused(self, enabled):
        GraphFactory()

        with pytest.raises(CommandError, match="self-hosted"):
            call_command("embed_glyphs", "--encoder", "claude", stdout=StringIO())
