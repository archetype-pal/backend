import hashlib
import json

from django.db import migrations, models

BATCH = 2000


def _crop_digest(image_path, outline):
    # `GlyphEmbedding.crop_digest_of`, as it stands at this migration.
    source = json.dumps({"image": image_path or "", "outline": outline}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(source.encode()).hexdigest()


def stamp_existing_vectors(apps, schema_editor):
    """Stamp each vector with the crop its glyph has now.

    No record says what a vector made before this migration was cut from. Its
    glyph's present outline and page image are the best evidence, so they are
    taken to be the source: the vector stays searchable. A glyph redrawn
    between its embedding and this migration keeps its stale vector until it
    is embedded again with `--force`.
    """
    GlyphEmbedding = apps.get_model("vision", "GlyphEmbedding")
    rows = GlyphEmbedding.objects.values_list("pk", "graph__item_image__image", "graph__annotation")
    batch = []
    for pk, image_path, outline in rows.iterator(chunk_size=BATCH):
        batch.append(GlyphEmbedding(pk=pk, crop_digest=_crop_digest(image_path, outline)))
        if len(batch) == BATCH:
            GlyphEmbedding.objects.bulk_update(batch, ["crop_digest"])
            batch = []
    GlyphEmbedding.objects.bulk_update(batch, ["crop_digest"])


class Migration(migrations.Migration):
    dependencies = [
        ("vision", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="glyphembedding",
            name="crop_digest",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(stamp_existing_vectors, migrations.RunPython.noop),
    ]
