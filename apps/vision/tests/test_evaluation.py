"""Scoring a glyph encoder by its nearest neighbours (W1.2, through W0.3).

The vectors are written by hand as directions in a plane, each glyph at an
angle, so the cosine between two glyphs is the cosine of the angle between
them and which glyph is nearest which is known before anything is scored.
"""

from collections.abc import Sequence
from io import StringIO
import json
import math
from pathlib import Path

from django.core.management import CommandError, call_command
from django.utils import timezone
import numpy as np
import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphComponentFactory, GraphFactory
from apps.ml.evaluation import load_release
from apps.ml.models import EvaluationRun
from apps.symbols_structure.tests.factories import ComponentFactory, FeatureFactory
from apps.vision.models import GlyphEmbedding
from apps.vision.services import evaluation
from apps.vision.services.evaluation import (
    EncoderEvaluationError,
    description_vectors,
    fuse,
    load_vectors,
    nearest,
    score_encoder,
    vote,
)

pytestmark = pytest.mark.django_db

TRAIN, HELD = 1, 2
WEIGHTS = {
    "trocr": ("LaMOP/TrOCR_Manicule_2026_Latin_Medieval", "08e146d2"),
    "pixels": ("raw-pixels", "16x16-grey-1"),
}


def _towards(degrees: float) -> list[float]:
    return [math.cos(math.radians(degrees)), math.sin(math.radians(degrees))]


def _embed(graph_id: int, vector: list[float], *, encoder: str = "trocr", version: str | None = None) -> None:
    model_name, model_version = WEIGHTS[encoder]
    GlyphEmbedding.objects.create(
        graph_id=graph_id,
        encoder=encoder,
        model_name=model_name,
        model_version=version or model_version,
        dimensions=len(vector),
        vector=GlyphEmbedding.pack(vector),
    )


def _describe(graph: Graph, components: dict) -> None:
    """Mark `components` on `graph`, each with the features listed for it."""
    for component, marked in components.items():
        GraphComponentFactory(graph=graph, component=component).features.add(*marked)


def _corpus(tmp_path: Path, glyphs: Sequence[tuple[int, str | None, float | None]]) -> tuple[Path, list[int]]:
    """A release of `(charter, allograph, angle)` glyphs, charter 2 held out.

    A glyph whose angle is None has no vector. An allograph's character is the
    part before any hyphen, so "s-long" and "s-round" are forms of one letter.
    """
    rows, ids = [], []
    for charter, allograph, angle in glyphs:
        graph = GraphFactory()
        if angle is not None:
            _embed(graph.pk, _towards(angle))
        ids.append(graph.pk)
        rows.append(
            {
                "graph_id": graph.pk,
                "item_part_id": charter,
                "repository": f"R{charter}",
                "allograph": allograph,
                "character": allograph.split("-")[0] if allograph else None,
            }
        )
    root = tmp_path / "v-test"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"version": "v-test"}))
    (root / "splits.json").write_text(
        json.dumps(
            {
                "by_charter": {"train": [TRAIN], "held_out": [HELD]},
                "by_repository": {"train": [f"R{TRAIN}"], "held_out": [f"R{HELD}"]},
            }
        )
    )
    (root / "glyphs.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return root, ids


def _score(root: Path, **kwargs) -> evaluation.EncoderScore:
    return score_encoder(load_release(root), load_vectors("trocr"), **kwargs)


class TestNearest:
    def test_lists_the_most_similar_training_rows_first(self):
        train = np.array([_towards(angle) for angle in (0, 30, 60, 90)], dtype=np.float32)
        queries = np.array([_towards(50), _towards(5)], dtype=np.float32)

        positions, similarities = nearest(train, queries, 3)

        assert positions.tolist() == [[2, 1, 3], [0, 1, 2]]
        assert similarities[0].tolist() == pytest.approx([math.cos(math.radians(d)) for d in (10, 20, 40)])

    def test_breaks_ties_by_training_position(self):
        # Seven rows tie for the query; the first three by position are its three nearest.
        train = np.array([[0, 1], [1, 0], [0, 1]] + [[1, 0]] * 6, dtype=np.float32)

        positions, _ = nearest(train, np.array([[1, 0]], dtype=np.float32), 3)

        assert positions.tolist() == [[1, 3, 4]]

    def test_a_blank_crop_s_neighbours_are_the_first_training_rows(self):
        # A zero vector ties with every glyph. Choosing five of seven equal
        # rows by partition alone does not pick the first five.
        train = np.random.default_rng(1).standard_normal((7, 4)).astype(np.float32)

        positions, _ = nearest(train, np.zeros((1, 4), dtype=np.float32), 5)

        assert positions.tolist() == [[0, 1, 2, 3, 4]]

    def test_gives_the_same_answer_however_the_queries_are_chunked(self, monkeypatch):
        rng = np.random.default_rng(7)
        train = rng.standard_normal((40, 8)).astype(np.float32)
        queries = rng.standard_normal((9, 8)).astype(np.float32)
        whole = nearest(train, queries, 5)

        monkeypatch.setattr(evaluation, "CHUNK", 2)
        chunked = nearest(train, queries, 5)

        assert chunked[0].tolist() == whole[0].tolist()
        # BLAS may sum a smaller product in another order: the same to float precision.
        np.testing.assert_allclose(chunked[1], whole[1], rtol=1e-5)

    def test_asks_for_no_more_neighbours_than_there_are(self):
        positions, _ = nearest(np.eye(2, dtype=np.float32), np.eye(2, dtype=np.float32), 10)

        assert positions.shape == (2, 2)


class TestVote:
    def test_the_label_carrying_the_most_similarity_wins(self):
        assert vote(["a", "b", "b"], [0.9, 0.5, 0.5]) == "b"

    def test_a_tie_goes_to_the_nearest_neighbour_s_label(self):
        assert vote(["a", "b", "b"], [1.0, 0.5, 0.5]) == "a"
        assert vote(["b", "a"], [0.5, 0.5]) == "b"


class TestLoadVectors:
    def test_refuses_an_encoder_with_no_vectors(self):
        with pytest.raises(EncoderEvaluationError, match="No glyph has a vector from 'trocr'"):
            load_vectors("trocr")

    def test_refuses_vectors_from_two_sets_of_weights(self):
        _embed(GraphFactory().pk, [1.0, 0.0], version="08e146d2")
        _embed(GraphFactory().pk, [1.0, 0.0], version="0b1c2d3e")

        with pytest.raises(EncoderEvaluationError, match="2 different weights"):
            load_vectors("trocr")

    def test_reads_only_the_named_encoder_and_scales_its_vectors_to_unit_length(self):
        long, blank, other = GraphFactory(), GraphFactory(), GraphFactory()
        _embed(long.pk, [3.0, 4.0])
        _embed(blank.pk, [0.0, 0.0])
        _embed(other.pk, [1.0, 0.0, 0.0], encoder="pixels")

        vectors = load_vectors("trocr")

        assert (vectors.model_name, vectors.model_version) == WEIGHTS["trocr"]
        assert set(vectors.index) == {long.pk, blank.pk}
        assert vectors.matrix[vectors.index[long.pk]].tolist() == pytest.approx([0.6, 0.8])
        # A blank crop's vector stays zero rather than turning into NaN.
        assert vectors.matrix[vectors.index[blank.pk]].tolist() == [0.0, 0.0]


class TestDescriptionVectors:
    def test_two_glyphs_are_as_alike_as_their_components_and_features_overlap(self):
        bowl, stem = ComponentFactory(), ComponentFactory()
        round_, split, curved = FeatureFactory(), FeatureFactory(), FeatureFactory()
        first, second = GraphFactory(), GraphFactory()
        _describe(first, {bowl: [round_, split]})
        _describe(second, {bowl: [round_], stem: [curved]})

        vectors = description_vectors()
        similarity = vectors.matrix[vectors.index[first.pk]] @ vectors.matrix[vectors.index[second.pk]]

        # bowl, bowl+round and bowl+split against bowl, bowl+round, stem and stem+curved: two shared of 3 and 4.
        assert similarity == pytest.approx(2 / math.sqrt(3 * 4))
        assert np.linalg.norm(vectors.matrix, axis=1).tolist() == pytest.approx([1.0, 1.0])
        assert (vectors.encoder, vectors.model_name, vectors.model_version) == (
            "descriptions",
            "digipal-descriptions",
            "components-features-1",
        )

    def test_a_component_marked_with_no_feature_counts_on_a_described_glyph(self):
        bowl, stem = ComponentFactory(), ComponentFactory()
        round_ = FeatureFactory()
        first, second = GraphFactory(), GraphFactory()
        _describe(first, {bowl: [round_], stem: []})
        _describe(second, {bowl: [round_]})

        vectors = description_vectors()
        similarity = vectors.matrix[vectors.index[first.pk]] @ vectors.matrix[vectors.index[second.pk]]

        # bowl, bowl+round and stem against bowl and bowl+round.
        assert similarity == pytest.approx(2 / math.sqrt(3 * 2))

    def test_only_a_live_image_glyph_with_a_feature_is_described(self):
        bowl, round_ = ComponentFactory(), FeatureFactory()
        described = GraphFactory()
        _describe(described, {bowl: [round_]})
        _describe(GraphFactory(), {bowl: []})
        _describe(GraphFactory(annotation_type=Graph.AnnotationType.TEXT), {bowl: [round_]})
        _describe(GraphFactory(deleted_at=timezone.now()), {bowl: [round_]})
        GraphFactory()

        assert list(description_vectors().index) == [described.pk]

    def test_refuses_when_no_glyph_is_described(self):
        _describe(GraphFactory(), {ComponentFactory(): []})

        with pytest.raises(EncoderEvaluationError, match="No glyph is described"):
            description_vectors()

    def test_are_what_load_vectors_reads_for_descriptions_and_fuse_with_an_encoder(self):
        bowl, round_ = ComponentFactory(), FeatureFactory()
        first, second = GraphFactory(), GraphFactory()
        for graph, angle in ((first, 0), (second, 60)):
            _describe(graph, {bowl: [round_]})
            _embed(graph.pk, _towards(angle))

        fused = fuse([load_vectors("descriptions"), load_vectors("trocr")])
        similarity = fused.matrix[fused.index[first.pk]] @ fused.matrix[fused.index[second.pk]]

        # Described alike (1) and 60 degrees apart (0.5).
        assert similarity == pytest.approx((1 + 0.5) / 2)
        assert fused.encoder == "descriptions+trocr"


class TestFuse:
    def test_a_fused_similarity_is_the_mean_of_the_parts(self):
        first, second = GraphFactory(), GraphFactory()
        for graph, (trocr, pixels) in ((first, (0, 0)), (second, (60, 90))):
            _embed(graph.pk, _towards(trocr))
            _embed(graph.pk, _towards(pixels), encoder="pixels")

        fused = fuse([load_vectors("trocr"), load_vectors("pixels")])
        similarity = fused.matrix[fused.index[first.pk]] @ fused.matrix[fused.index[second.pk]]

        assert similarity == pytest.approx((math.cos(math.radians(60)) + math.cos(math.radians(90))) / 2)
        assert np.linalg.norm(fused.matrix, axis=1).tolist() == pytest.approx([1.0, 1.0])

    def test_keeps_the_glyphs_every_part_has_and_is_named_after_its_parts(self):
        both, only_trocr = GraphFactory(), GraphFactory()
        _embed(both.pk, [1.0, 0.0])
        _embed(only_trocr.pk, [1.0, 0.0])
        _embed(both.pk, [0.0, 1.0, 0.0], encoder="pixels")

        fused = fuse([load_vectors("trocr"), load_vectors("pixels")])

        assert list(fused.index) == [both.pk]
        assert fused.matrix.shape == (1, 5)
        assert (fused.encoder, fused.model_name, fused.model_version) == (
            "trocr+pixels",
            "LaMOP/TrOCR_Manicule_2026_Latin_Medieval+raw-pixels",
            "08e146d2+16x16-grey-1",
        )

    def test_refuses_one_encoder_or_parts_with_no_glyph_in_common(self):
        first, second = GraphFactory(), GraphFactory()
        _embed(first.pk, [1.0, 0.0])
        _embed(second.pk, [1.0, 0.0], encoder="pixels")

        with pytest.raises(EncoderEvaluationError, match="at least two"):
            fuse([load_vectors("trocr")])
        with pytest.raises(EncoderEvaluationError, match="No glyph has a vector from every encoder"):
            fuse([load_vectors("trocr"), load_vectors("pixels")])

    def test_weights_make_it_a_weighted_mean_and_are_named(self):
        first, second = GraphFactory(), GraphFactory()
        for graph, (trocr, pixels) in ((first, (0, 0)), (second, (60, 90))):
            _embed(graph.pk, _towards(trocr))
            _embed(graph.pk, _towards(pixels), encoder="pixels")

        fused = fuse([load_vectors("trocr"), load_vectors("pixels")], {"trocr": 3})
        similarity = fused.matrix[fused.index[first.pk]] @ fused.matrix[fused.index[second.pk]]

        assert similarity == pytest.approx((3 * math.cos(math.radians(60)) + math.cos(math.radians(90))) / 4)
        assert np.linalg.norm(fused.matrix, axis=1).tolist() == pytest.approx([1.0, 1.0])
        assert (fused.encoder, fused.model_name) == (
            "3*trocr+pixels",
            "3*LaMOP/TrOCR_Manicule_2026_Latin_Medieval+raw-pixels",
        )

    def test_refuses_weights_for_encoders_not_fused_or_not_above_zero(self):
        graph = GraphFactory()
        _embed(graph.pk, [1.0, 0.0])
        _embed(graph.pk, [1.0, 0.0], encoder="pixels")
        parts = [load_vectors("trocr"), load_vectors("pixels")]

        with pytest.raises(EncoderEvaluationError, match="not being fused: ink"):
            fuse(parts, {"ink": 2})
        with pytest.raises(EncoderEvaluationError, match="greater than 0"):
            fuse(parts, {"pixels": 0})


class TestScoreEncoder:
    def test_each_held_out_glyph_takes_its_nearest_training_glyph_s_allograph(self, tmp_path):
        root, _ = _corpus(
            tmp_path,
            [(TRAIN, "a", 0), (TRAIN, "b", 90), (HELD, "a", 10), (HELD, "b", 70), (HELD, "a", 80)],
        )

        result = _score(root)

        assert result.metrics.n == 3
        assert result.metrics.accuracy == pytest.approx(2 / 3)

    def test_held_out_glyphs_are_never_each_other_s_neighbours(self, tmp_path):
        # The two "c"s are each other's closest glyph, but both are held out,
        # and no training glyph is a "c".
        root, _ = _corpus(tmp_path, [(TRAIN, "a", 0), (TRAIN, "b", 90), (HELD, "c", 40), (HELD, "c", 41)])

        assert _score(root).metrics.accuracy == 0.0

    def test_scores_only_labelled_glyphs_that_have_a_vector_and_says_how_many(self, tmp_path):
        root, _ = _corpus(
            tmp_path,
            [
                (TRAIN, "a", 0),
                (TRAIN, "b", 90),
                (TRAIN, "b", None),
                (HELD, "a", 10),
                (HELD, "b", 80),
                (HELD, "a", None),
                (HELD, None, 45),
            ],
        )

        result = _score(root)

        assert (result.train_scored, result.train_total) == (2, 3)
        assert (result.held_scored, result.held_total) == (2, 3)
        assert result.metrics.n == 2
        assert "Scored on 2 of 3 held-out glyphs" in result.notes("by_charter")
        assert "from 2 of 3 training glyphs" in result.notes("by_charter")

    def test_the_baselines_are_scored_on_the_same_glyphs_from_the_same_training_glyphs(self, tmp_path):
        # Most training glyphs are "b", but those have no vector; among the
        # glyphs scored, "a" is the commonest, so the majority guess is "a".
        root, _ = _corpus(
            tmp_path,
            [(TRAIN, "a", 0), (TRAIN, "a", 5), (TRAIN, "b", 90)]
            + [(TRAIN, "b", None)] * 3
            + [(HELD, "a", 10), (HELD, "a", 20), (HELD, "b", 85), (HELD, "b", None)],
        )

        result = _score(root)

        assert result.majority.n == result.stratified.n == result.metrics.n == 3
        assert result.majority.accuracy == pytest.approx(2 / 3)

    def test_with_more_neighbours_the_label_they_carry_most_similarity_for_wins(self, tmp_path):
        # The nearest is an "a" (5°), but two "b"s at 15° and 20° outweigh it.
        root, _ = _corpus(tmp_path, [(TRAIN, "a", 0), (TRAIN, "b", 20), (TRAIN, "b", 25), (HELD, "a", 5)])

        assert _score(root, k=1).metrics.accuracy == 1.0
        assert _score(root, k=3).metrics.accuracy == 0.0

    def test_character_accuracy_forgives_the_wrong_form_of_the_right_letter(self, tmp_path):
        root, _ = _corpus(tmp_path, [(TRAIN, "s-long", 0), (TRAIN, "a", 90), (HELD, "s-round", 10)])

        result = _score(root)

        assert result.metrics.accuracy == 0.0
        assert result.character_accuracy == 1.0

    def test_precision_at_10_counts_the_ten_nearest_training_glyphs(self, tmp_path):
        # Six "a"s and six "b"s. Each held-out glyph's ten nearest are its own
        # six and the four nearest of the other: 6 of 10.
        root, _ = _corpus(
            tmp_path,
            [(TRAIN, "a", angle) for angle in range(6)]
            + [(TRAIN, "b", 30 + angle) for angle in range(6)]
            + [(HELD, "a", 0), (HELD, "b", 35)],
        )

        assert _score(root).precision_at_10 == pytest.approx(0.6)

    def test_precision_at_10_over_fewer_training_glyphs_counts_all_of_them(self, tmp_path):
        root, _ = _corpus(
            tmp_path, [(TRAIN, "a", 0), (TRAIN, "a", 10), (TRAIN, "b", 20), (TRAIN, "b", 100), (HELD, "a", 5)]
        )

        assert _score(root).precision_at_10 == pytest.approx(0.5)

    def test_only_restricts_both_sides_to_the_glyphs_named(self, tmp_path):
        root, ids = _corpus(
            tmp_path, [(TRAIN, "a", 0), (TRAIN, "b", 12), (HELD, "a", 10), (HELD, "b", 80), (HELD, "a", 85)]
        )
        a_train, _, a_held, b_held, _ = ids

        # Without the "b" at 12°, the held-out "a" at 10° is nearest the "a".
        result = _score(root, only={a_train, a_held, b_held})

        assert (result.train_scored, result.held_scored) == (1, 2)
        assert result.metrics.accuracy == 0.5

    def test_refuses_fewer_than_one_neighbour(self, tmp_path):
        root, _ = _corpus(tmp_path, [(TRAIN, "a", 0), (HELD, "a", 10)])

        with pytest.raises(EncoderEvaluationError, match="at least 1"):
            _score(root, k=0)

    def test_refuses_when_nothing_held_out_has_a_vector(self, tmp_path):
        root, _ = _corpus(tmp_path, [(TRAIN, "a", 0), (HELD, "a", None)])

        with pytest.raises(EncoderEvaluationError, match="Nothing to score: 1 training and 0 held-out"):
            _score(root)


class TestCommand:
    @pytest.fixture
    def two_encoders(self, tmp_path):
        """trocr and pixels over one release; trocr is missing a held-out glyph."""
        root, ids = _corpus(
            tmp_path, [(TRAIN, "a", 0), (TRAIN, "b", 90), (HELD, "a", 10), (HELD, "b", 80), (HELD, "b", None)]
        )
        for graph_id, angle in zip(ids, (0, 90, 60, 30, 85), strict=True):
            _embed(graph_id, _towards(angle), encoder="pixels")
        return root

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("eval_glyph_encoder", *args, stdout=out)
        return out.getvalue()

    def test_scores_every_encoder_on_the_glyphs_all_of_them_have(self, two_encoders):
        output = self._run("--release", str(two_encoders), "--encoder", "trocr", "--encoder", "pixels")

        assert "held out 2 of 3 labelled glyphs" in output
        assert "trocr (LaMOP/TrOCR_Manicule_2026_Latin_Medieval@08e146d2)\n  allograph accuracy=1.0000" in output
        assert "pixels (raw-pixels@16x16-grey-1)\n  allograph accuracy=0.0000" in output
        assert not EvaluationRun.objects.exists()

    def test_records_one_run_per_encoder_against_the_majority_baseline(self, two_encoders):
        output = self._run("--release", str(two_encoders), "--encoder", "trocr", "--encoder", "pixels", "--record")

        runs = {run.model_name: run for run in EvaluationRun.objects.all()}
        assert set(runs) == {"LaMOP/TrOCR_Manicule_2026_Latin_Medieval", "raw-pixels"}
        for run in runs.values():
            assert (run.task, run.release, run.split, run.baseline_name) == ("W1.2", "v-test", "by_charter", "majority")
            assert run.metrics["n"] == run.baseline_metrics["n"] == 2
            assert "Scored on 2 of 3 held-out glyphs" in run.notes
        assert runs["LaMOP/TrOCR_Manicule_2026_Latin_Medieval"].model_version == "08e146d2"
        assert runs["LaMOP/TrOCR_Manicule_2026_Latin_Medieval"].beats_baseline
        assert not runs["raw-pixels"].beats_baseline
        assert "beats the majority baseline" in output
        assert "DOES NOT BEAT the majority baseline" in output

    def test_fusing_scores_the_encoders_as_one_and_records_it_too(self, two_encoders):
        # Pixels alone puts each held-out glyph nearer the wrong training glyph;
        # averaged with trocr, the right one is nearer.
        output = self._run(
            "--release", str(two_encoders), "--encoder", "trocr", "--encoder", "pixels", "--fuse", "--record"
        )

        fused = (
            "trocr+pixels (LaMOP/TrOCR_Manicule_2026_Latin_Medieval+raw-pixels@08e146d2+16x16-grey-1)\n"
            "  allograph accuracy=1.0000"
        )
        assert fused in output
        assert "pixels (raw-pixels@16x16-grey-1)\n  allograph accuracy=0.0000" in output
        run = EvaluationRun.objects.get(model_name="LaMOP/TrOCR_Manicule_2026_Latin_Medieval+raw-pixels")
        assert (run.model_version, run.metrics["n"], run.task) == ("08e146d2+16x16-grey-1", 2, "W1.2")
        assert EvaluationRun.objects.count() == 3

    def test_a_weight_changes_what_the_fusion_finds(self, two_encoders):
        # Weighted nine to one towards pixels, the fusion makes pixels' mistakes.
        output = self._run(
            "--release",
            str(two_encoders),
            "--encoder",
            "trocr",
            "--encoder",
            "pixels",
            "--fuse",
            "--weight",
            "pixels=9",
        )

        fused = output[output.index("trocr+9*pixels (LaMOP/TrOCR_Manicule_2026_Latin_Medieval+9*raw-pixels@") :]
        assert fused.splitlines()[1].startswith("  allograph accuracy=0.0000")

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--weight", "pixels=2"], "only applies with --fuse"),
            (["--fuse", "--weight", "pixels"], "ENCODER=NUMBER"),
            (["--fuse", "--weight", "ink=2"], "not being fused: ink"),
        ],
    )
    def test_says_what_is_wrong_with_a_weight(self, two_encoders, args, message):
        with pytest.raises(CommandError, match=message):
            self._run("--release", str(two_encoders), "--encoder", "trocr", "--encoder", "pixels", *args)

    def test_scores_descriptions_and_only_described_glyphs_when_asked(self, two_encoders):
        bowl, stem, round_ = ComponentFactory(), ComponentFactory(), FeatureFactory()
        glyphs = [row["graph_id"] for row in load_release(two_encoders).glyphs]
        # Both training glyphs and the first held-out one, which is described as the second training glyph is.
        _describe(Graph.objects.get(pk=glyphs[0]), {bowl: [round_]})
        _describe(Graph.objects.get(pk=glyphs[1]), {stem: [round_]})
        _describe(Graph.objects.get(pk=glyphs[2]), {stem: [round_]})

        everything = self._run("--release", str(two_encoders), "--encoder", "trocr")
        described = self._run("--release", str(two_encoders), "--encoder", "trocr", "--described")
        legacy = self._run("--release", str(two_encoders), "--encoder", "descriptions", "--encoder", "trocr")

        assert "held out 2 of 3 labelled glyphs" in everything
        assert "held out 1 of 3 labelled glyphs" in described
        assert "trocr (LaMOP/TrOCR_Manicule_2026_Latin_Medieval@08e146d2)\n  allograph accuracy=1.0000" in described
        assert "held out 1 of 3 labelled glyphs" in legacy
        assert "descriptions (digipal-descriptions@components-features-1)\n  allograph accuracy=0.0000" in legacy

    def test_refuses_to_score_only_described_glyphs_when_none_is(self, two_encoders):
        with pytest.raises(CommandError, match="No glyph is described"):
            self._run("--release", str(two_encoders), "--described")

    def test_scores_trocr_when_no_encoder_is_named(self, two_encoders):
        output = self._run("--release", str(two_encoders), "--k", "2", "--split", "by_repository")

        assert "split by_repository · k=2" in output
        assert "trocr (" in output
        assert "pixels (" not in output

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--release", "/nowhere"], "is not a release"),
            (["--encoder", "nobody"], "No glyph has a vector from 'nobody'"),
            (["--split", "by_moon"], "has no split 'by_moon'"),
        ],
    )
    def test_says_what_it_cannot_score(self, two_encoders, args, message):
        args = args if args[0] == "--release" else ["--release", str(two_encoders), *args]

        with pytest.raises(CommandError, match=message):
            self._run(*args)
