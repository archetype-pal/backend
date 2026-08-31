"""The evaluation harness — AI programme W0.3.

The rule under test is the release rule: no model ships without numbers, and no
number ships without its split and its baseline. The harness's job is to make
that unskippable, so most of these tests are about what it *refuses*.
"""

import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from apps.ml import evaluation as harness
from apps.ml.models import EvaluationRun
from apps.ml.services import evaluation as service


def _release(tmp_path: Path, *, version="v1", rows=None, held_out_charters=(2,)) -> Path:
    rows = rows or [
        {"graph_id": 1, "item_part_id": 1, "repository": "AAA", "allograph": "a"},
        {"graph_id": 2, "item_part_id": 1, "repository": "AAA", "allograph": "a"},
        {"graph_id": 3, "item_part_id": 1, "repository": "AAA", "allograph": "b"},
        {"graph_id": 4, "item_part_id": 2, "repository": "BBB", "allograph": "a"},
        {"graph_id": 5, "item_part_id": 2, "repository": "BBB", "allograph": "b"},
    ]
    root: Path = tmp_path / version
    root.mkdir(parents=True, exist_ok=True)
    charters = sorted({row["item_part_id"] for row in rows})
    repos = sorted({row["repository"] for row in rows})
    (root / "manifest.json").write_text(json.dumps({"version": version}))
    (root / "splits.json").write_text(
        json.dumps(
            {
                "by_charter": {
                    "train": [c for c in charters if c not in held_out_charters],
                    "held_out": list(held_out_charters),
                },
                "by_repository": {"train": repos[:1], "held_out": repos[1:]},
            }
        )
    )
    (root / "glyphs.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return root


class TestScoring:
    def test_perfect_predictions(self):
        metrics = harness.score(["a", "b", "a"], ["a", "b", "a"])

        assert metrics.accuracy == 1.0
        assert metrics.macro_f1 == 1.0
        assert metrics.per_class["a"]["support"] == 2

    def test_all_wrong(self):
        assert harness.score(["a", "a"], ["b", "b"]).accuracy == 0.0

    def test_per_class_support_travels_with_the_score(self):
        """A per-class number without its support is not interpretable."""
        metrics = harness.score(["a", "a", "a", "b"], ["a", "a", "a", "a"])

        assert metrics.per_class["b"]["support"] == 1
        assert metrics.per_class["b"]["recall"] == 0.0

    def test_a_hallucinated_class_does_not_dilute_macro_f1(self):
        """Macro-F1 averages over classes present in the truth, not invented ones."""
        metrics = harness.score(["a", "a"], ["a", "zzz"])

        assert "zzz" in metrics.per_class
        assert metrics.per_class["zzz"]["support"] == 0
        assert metrics.macro_f1 == pytest.approx(harness.score(["a", "a"], ["a", "q"]).macro_f1)

    def test_mismatched_lengths_are_an_error(self):
        with pytest.raises(ValueError, match="Mismatched lengths"):
            harness.score(["a"], ["a", "b"])

    def test_scoring_nothing_is_an_error(self):
        with pytest.raises(ValueError, match="Nothing to score"):
            harness.score([], [])


class TestBaselines:
    def test_majority_predicts_the_commonest_training_class(self):
        assert harness.majority_baseline(["a", "a", "b"], 3) == ["a", "a", "a"]

    def test_stratified_is_reproducible_from_the_release_version(self):
        """A floor that moves between runs is not a floor."""
        labels = ["a"] * 10 + ["b"] * 5
        first = harness.stratified_baseline(labels, 20, seed="v1")
        second = harness.stratified_baseline(labels, 20, seed="v1")

        assert first == second
        assert first != harness.stratified_baseline(labels, 20, seed="v2")

    def test_the_pixel_baseline_is_declared_unavailable_not_silently_skipped(self):
        assert "pixel-free release carries none" in harness.PIXEL_BASELINE_UNAVAILABLE


class TestRelease:
    def test_partition_is_grouped_by_charter(self, tmp_path: Path):
        release = harness.load_release(_release(tmp_path))

        train, held_out = release.partition("by_charter")

        assert {row["item_part_id"] for row in train} == {1}
        assert {row["item_part_id"] for row in held_out} == {2}

    def test_no_glyph_appears_on_both_sides(self, tmp_path: Path):
        release = harness.load_release(_release(tmp_path))

        train, held_out = release.partition("by_charter")

        assert not {r["graph_id"] for r in train} & {r["graph_id"] for r in held_out}

    def test_partition_by_repository(self, tmp_path: Path):
        release = harness.load_release(_release(tmp_path))

        _, held_out = release.partition("by_repository")

        assert {row["repository"] for row in held_out} == {"BBB"}

    def test_an_unknown_split_is_an_error(self, tmp_path: Path):
        release = harness.load_release(_release(tmp_path))

        with pytest.raises(harness.ReleaseError, match="no split"):
            release.partition("by_vibes")

    def test_an_incomplete_directory_is_not_a_release(self, tmp_path: Path):
        (tmp_path / "empty").mkdir()

        with pytest.raises(harness.ReleaseError, match="missing"):
            harness.load_release(tmp_path / "empty")


@pytest.mark.django_db
class TestRecordingRefuses:
    def _metrics(self, n=2):
        return harness.score(["a"] * n, ["a"] * n)

    def _kwargs(self, **overrides):
        base = dict(
            model_name="detector",
            task="W1.1",
            release="v1",
            split="by_charter",
            metrics=self._metrics(),
            baseline_name="majority",
            baseline_metrics=self._metrics(),
        )
        base.update(overrides)
        return base

    def test_a_complete_run_is_recorded(self):
        run = service.record_run(**self._kwargs())

        assert EvaluationRun.objects.count() == 1
        assert run.beats_baseline is False  # identical scores do not "beat"

    def test_a_run_without_a_release_is_refused(self):
        with pytest.raises(service.EvaluationError, match="name the release"):
            service.record_run(**self._kwargs(release=""))

        assert EvaluationRun.objects.count() == 0

    def test_a_run_without_a_split_is_refused(self):
        with pytest.raises(service.EvaluationError, match="name its split"):
            service.record_run(**self._kwargs(split=""))

    def test_a_run_without_a_baseline_is_refused(self):
        """A number with no floor beside it is not a result."""
        with pytest.raises(service.EvaluationError, match="must carry a baseline"):
            service.record_run(**self._kwargs(baseline_name=""))

    def test_a_baseline_scored_on_a_different_set_is_refused(self):
        with pytest.raises(service.EvaluationError, match="different sets"):
            service.record_run(**self._kwargs(baseline_metrics=self._metrics(n=5)))

    def test_beats_baseline_is_reported_not_assumed(self):
        run = service.record_run(
            **self._kwargs(
                metrics=harness.score(["a", "b"], ["a", "b"]),
                baseline_metrics=harness.score(["a", "b"], ["a", "a"]),
            )
        )

        assert run.beats_baseline is True


@pytest.mark.django_db
class TestCommand:
    def test_baselines_report_the_floor_before_any_model_exists(self, tmp_path: Path, capsys):
        call_command("ml_eval", "--release", str(_release(tmp_path)), "--baselines")

        out = capsys.readouterr().out
        assert "baselines — the floor a model must clear" in out
        assert "majority" in out
        assert "pixel-free release carries none" in out

    def test_scoring_records_a_run(self, tmp_path: Path):
        root = _release(tmp_path)
        preds = tmp_path / "preds.jsonl"
        preds.write_text('{"graph_id": 4, "allograph": "a"}\n{"graph_id": 5, "allograph": "b"}\n')

        call_command(
            "ml_eval",
            "--release",
            str(root),
            "--predictions",
            str(preds),
            "--model",
            "detector",
            "--task",
            "W1.1",
        )

        run = EvaluationRun.objects.get()
        assert run.metrics["accuracy"] == 1.0
        assert run.baseline_name == "majority"
        assert run.release == "v1"

    def test_a_partial_prediction_set_is_refused(self, tmp_path: Path):
        """Scoring only the rows a model answered would inflate the number."""
        root = _release(tmp_path)
        preds = tmp_path / "preds.jsonl"
        preds.write_text('{"graph_id": 4, "allograph": "a"}\n')

        with pytest.raises(CommandError, match="no prediction"):
            call_command(
                "ml_eval",
                "--release",
                str(root),
                "--predictions",
                str(preds),
                "--model",
                "detector",
                "--task",
                "W1.1",
            )

        assert EvaluationRun.objects.count() == 0

    def test_a_malformed_predictions_file_is_refused(self, tmp_path: Path):
        root = _release(tmp_path)
        preds = tmp_path / "preds.jsonl"
        preds.write_text("not json\n")

        with pytest.raises(CommandError, match="is not a"):
            call_command("ml_eval", "--release", str(root), "--predictions", str(preds))

    def test_list_reports_recorded_runs(self, tmp_path: Path, capsys):
        service.record_run(
            model_name="detector",
            task="W1.1",
            release="v1",
            split="by_charter",
            metrics=harness.score(["a"], ["a"]),
            baseline_name="majority",
            baseline_metrics=harness.score(["a"], ["b"]),
        )

        call_command("ml_eval", "--list")

        assert "detector" in capsys.readouterr().out

    def test_list_with_nothing_recorded(self, capsys):
        call_command("ml_eval", "--list")

        assert "No evaluation runs recorded." in capsys.readouterr().out
