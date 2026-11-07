"""Evaluate a model against a frozen release, or show what it must beat (W0.3).

    manage.py ml_eval --release storage/releases/v1 --baselines
    manage.py ml_eval --release storage/releases/v1 --predictions preds.jsonl \\
                      --model detector --model-version 2026-09 --task W1.1
    manage.py ml_eval --list

`--baselines` is useful before any model exists: it reports the floor a model
would have to clear on this release and this split, which is a number worth
knowing while the model is still being chosen rather than after.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.ml.evaluation import (
    PIXEL_BASELINE_UNAVAILABLE,
    ReleaseError,
    load_release,
    majority_baseline,
    score,
    stratified_baseline,
)
from apps.ml.services import evaluation

LABEL_FIELD = "allograph"


class Command(BaseCommand):
    help = "Score held-out predictions against a frozen dataset release, with baselines."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--release", help="Path to a release directory written by export_glyph_dataset.")
        parser.add_argument("--split", default="by_charter", help="Which split to hold out (default: by_charter).")
        parser.add_argument("--predictions", help="JSONL of {graph_id, allograph} predictions for the held-out set.")
        parser.add_argument("--model", default="", help="Model name, recorded with the run.")
        parser.add_argument("--model-version", default="", help="Model version, recorded with the run.")
        parser.add_argument("--task", default="", help="Programme item this evaluates, e.g. W1.1.")
        parser.add_argument("--baselines", action="store_true", help="Report the baselines and stop.")
        parser.add_argument("--list", action="store_true", help="List recorded runs and exit.")

    def handle(self, *args, **options) -> None:
        if options["list"]:
            self._list(options["task"])
            return
        if not options["release"]:
            raise CommandError("--release is required (or use --list).")

        try:
            release = load_release(options["release"])
            train, held_out = release.partition(options["split"])
        except ReleaseError as exc:
            raise CommandError(str(exc)) from None

        if not held_out:
            raise CommandError(f"Split '{options['split']}' holds out nothing in release {release.version}.")

        train_labels = [row[LABEL_FIELD] for row in train if row.get(LABEL_FIELD)]
        truth = [row[LABEL_FIELD] for row in held_out if row.get(LABEL_FIELD)]
        held_ids = [row["graph_id"] for row in held_out if row.get(LABEL_FIELD)]

        self.stdout.write(f"release {release.version} · split {options['split']}")
        self.stdout.write(f"  train {len(train_labels)} · held out {len(truth)}")

        majority = score(truth, majority_baseline(train_labels, len(truth)))
        stratified = score(truth, stratified_baseline(train_labels, len(truth), seed=release.version))
        self.stdout.write("")
        self.stdout.write("baselines — the floor a model must clear:")
        self.stdout.write(f"  majority    accuracy={majority.accuracy:.4f}  macro_f1={majority.macro_f1:.4f}")
        self.stdout.write(f"  stratified  accuracy={stratified.accuracy:.4f}  macro_f1={stratified.macro_f1:.4f}")
        self.stdout.write(self.style.WARNING(f"  note: {PIXEL_BASELINE_UNAVAILABLE}"))

        if options["baselines"] or not options["predictions"]:
            if not options["baselines"]:
                self.stdout.write("")
                self.stdout.write("No --predictions given; reported baselines only.")
            return

        predictions = self._load_predictions(options["predictions"])
        missing = [gid for gid in held_ids if gid not in predictions]
        if missing:
            raise CommandError(
                f"{len(missing)} held-out rows have no prediction (first: {missing[:3]}). "
                "Scoring a subset would inflate the number."
            )
        y_pred = [predictions[gid] for gid in held_ids]
        metrics = score(truth, y_pred)

        self.stdout.write("")
        self.stdout.write(f"model {options['model'] or '(unnamed)'}@{options['model_version'] or '?'}")
        self.stdout.write(f"  accuracy={metrics.accuracy:.4f}  macro_f1={metrics.macro_f1:.4f}")

        if not options["model"] or not options["task"]:
            self.stdout.write(self.style.WARNING("  not recorded: --model and --task are required to write a run."))
            return

        run = evaluation.record_run(
            model_name=options["model"],
            model_version=options["model_version"],
            task=options["task"],
            release=release.version,
            split=options["split"],
            metrics=metrics,
            baseline_name="majority",
            baseline_metrics=majority,
        )
        verdict = "beats" if run.beats_baseline else "DOES NOT BEAT"
        style = self.style.SUCCESS if run.beats_baseline else self.style.ERROR
        self.stdout.write(style(f"  recorded run {run.pk} — {verdict} the majority baseline."))

    def _list(self, task: str) -> None:
        rows = evaluation.latest_per_model(task)
        if not rows:
            self.stdout.write("No evaluation runs recorded.")
            return
        for row in rows:
            flag = "" if row["beats_baseline"] else "  ← does not beat baseline"
            self.stdout.write(
                f"{row['model']:<28} {row['task']:<8} {row['release']}/{row['split']:<14} "
                f"acc={row['accuracy']:.4f} (baseline {row['baseline']} {row['baseline_accuracy']:.4f}){flag}"
            )

    @staticmethod
    def _load_predictions(path: str) -> dict[int, str]:
        file = Path(path)
        if not file.is_file():
            raise CommandError(f"No predictions file at {file}.")
        out: dict[int, str] = {}
        with file.open(encoding="utf-8") as fh:
            for number, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    out[int(row["graph_id"])] = str(row[LABEL_FIELD])
                except (ValueError, KeyError) as exc:
                    raise CommandError(f"{file}:{number} is not a {{graph_id, {LABEL_FIELD}}} row ({exc}).") from None
        return out
