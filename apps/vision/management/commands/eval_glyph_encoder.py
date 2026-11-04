"""Score glyph encoders by their nearest neighbours on a frozen release (W1.2).

    manage.py eval_glyph_encoder --release storage/releases/v1
    manage.py eval_glyph_encoder --release storage/releases/v1 --encoder dinov2 --encoder pixels --record

Each encoder named is scored on the glyphs that every one of them has a vector
for, so their numbers compare. `--record` writes one evaluation run per encoder
(task W1.2, majority baseline), which `ml_eval --list` then shows.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.ml.evaluation import ReleaseError, load_release
from apps.ml.services import evaluation as runs
from apps.vision.services import evaluation

TASK = "W1.2"


class Command(BaseCommand):
    help = "Score glyph encoders by nearest neighbours on a frozen dataset release, with baselines."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--release", required=True, help="A release directory written by export_glyph_dataset.")
        parser.add_argument("--split", default="by_charter", help="Which split to hold out (default: by_charter).")
        parser.add_argument(
            "--encoder", action="append", help="An encoder whose vectors to score; repeat to compare (default: dinov2)."
        )
        parser.add_argument("--k", type=int, default=1, help="Neighbours that vote on a glyph's allograph (default 1).")
        parser.add_argument("--record", action="store_true", help="Record each encoder's run.")

    def handle(self, *args, **options) -> None:
        encoders = options["encoder"] or ["dinov2"]
        try:
            release = load_release(options["release"])
            vectors = [evaluation.load_vectors(encoder) for encoder in encoders]
        except (ReleaseError, evaluation.EncoderEvaluationError) as exc:
            raise CommandError(str(exc)) from None

        # Compare like with like: every encoder on the glyphs all of them have.
        shared = set.intersection(*(set(v.index) for v in vectors)) if len(vectors) > 1 else None
        try:
            scores = [
                evaluation.score_encoder(release, v, split=options["split"], k=options["k"], only=shared)
                for v in vectors
            ]
        except (ReleaseError, evaluation.EncoderEvaluationError) as exc:
            raise CommandError(str(exc)) from None

        first = scores[0]
        self.stdout.write(f"release {release.version} · split {options['split']} · k={options['k']}")
        self.stdout.write(
            f"  held out {first.held_scored} of {first.held_total} labelled glyphs (those with a vector) · "
            f"neighbours from {first.train_scored} of {first.train_total}"
        )
        self.stdout.write("")
        self.stdout.write("baselines on the same glyphs:")
        self.stdout.write(
            f"  majority    accuracy={first.majority.accuracy:.4f}  macro_f1={first.majority.macro_f1:.4f}"
        )
        self.stdout.write(
            f"  stratified  accuracy={first.stratified.accuracy:.4f}  macro_f1={first.stratified.macro_f1:.4f}"
        )
        self.stdout.write("")
        for result in scores:
            self.stdout.write(f"{result.encoder} ({result.model_name}@{result.model_version})")
            self.stdout.write(
                f"  allograph accuracy={result.metrics.accuracy:.4f}  macro_f1={result.metrics.macro_f1:.4f}  "
                f"character accuracy={result.character_accuracy:.4f}  "
                f"precision@{evaluation.PRECISION_AT}={result.precision_at_10:.4f}"
            )
            if options["record"]:
                run = runs.record_run(
                    model_name=result.model_name,
                    model_version=result.model_version,
                    task=TASK,
                    release=release.version,
                    split=options["split"],
                    metrics=result.metrics,
                    baseline_name="majority",
                    baseline_metrics=result.majority,
                    notes=result.notes(options["split"]),
                )
                verdict = "beats" if run.beats_baseline else "DOES NOT BEAT"
                style = self.style.SUCCESS if run.beats_baseline else self.style.ERROR
                self.stdout.write(style(f"  recorded run {run.pk}: {verdict} the majority baseline."))
