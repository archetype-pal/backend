"""Embed glyph annotations with a self-hosted encoder (AI programme W1.2).

    manage.py embed_glyphs                      # every glyph not yet embedded
    manage.py embed_glyphs --limit 200          # a trial run
    manage.py embed_glyphs --force              # re-embed, e.g. after new weights

Needs `ML_INFERENCE_ENABLED` and, for `trocr`, the embedder service at
`ML_EMBEDDER_URL`. Each batch is one ledger row. A glyph whose page the image
server cannot serve is counted as unavailable and skipped.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.vision.services import embedding


class Command(BaseCommand):
    help = "Turn glyph annotations into vectors with a self-hosted encoder."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--encoder", default=embedding.DEFAULT_ENCODER, help="A self-hosted provider.")
        parser.add_argument("--limit", type=int, help="Embed at most this many glyphs.")
        parser.add_argument("--batch-size", type=int, default=32, help="Glyphs per ledger row (default 32).")
        parser.add_argument("--force", action="store_true", help="Re-embed glyphs that already have a vector.")

    def handle(self, *args, **options) -> None:
        if not 1 <= options["batch_size"] <= 64:
            raise CommandError("--batch-size must be between 1 and 64, the encoder's limit per request.")
        graphs = embedding.glyphs_to_embed(options["encoder"], force=options["force"])
        total = graphs.count()
        if options["limit"] is not None:
            graphs = graphs[: options["limit"]]
            total = min(total, options["limit"])
        self.stdout.write(f"{total} glyphs to embed with {options['encoder']}.")
        if not total:
            return

        def progress(tally: embedding.Tally) -> None:
            done = tally.embedded + tally.unavailable + tally.failed
            self.stdout.write(f"  {done}/{total} · embedded {tally.embedded} · unavailable {tally.unavailable}")

        try:
            tally = embedding.embed_glyphs(
                graphs.iterator(chunk_size=500),
                encoder=options["encoder"],
                batch_size=options["batch_size"],
                on_batch=progress,
            )
        except embedding.EncoderNotAllowed as exc:
            raise CommandError(str(exc)) from None

        summary = ", ".join(f"{key} {value}" for key, value in tally.as_dict().items())
        if tally.refused:
            raise CommandError(f"Refused after {summary}: {tally.refused}")
        self.stdout.write(self.style.SUCCESS(f"Done: {summary}."))
