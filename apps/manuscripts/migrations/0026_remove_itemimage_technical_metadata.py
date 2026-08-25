"""Drop everything 0023 added to ItemImage; the row stays a pure reference.

The image server owns technical image details: dimensions come from SIPI's
`info.json` via `apps.manuscripts.iiif.resolve_image_dimensions`, so a second
copy here could only drift. The rest described the archived upload original,
which the ingest pipeline no longer keeps.

`created`/`modified` go too. `AddField` with auto_now_add fills existing rows
with the migration's own clock, so 0023 stamped the entire bulk-migrated corpus
with the instant it ran — a creation date for charter images scanned years
earlier. EditEvent already records upload time and actor for rows this app
creates, and correctly records nothing for the legacy corpus.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0025_merge_itemimage_metadata_msdescarea"),
    ]

    operations = [
        migrations.RemoveField(model_name="itemimage", name="checksum_sha256"),
        migrations.RemoveField(model_name="itemimage", name="created"),
        migrations.RemoveField(model_name="itemimage", name="exif"),
        migrations.RemoveField(model_name="itemimage", name="height"),
        migrations.RemoveField(model_name="itemimage", name="modified"),
        migrations.RemoveField(model_name="itemimage", name="original_path"),
        migrations.RemoveField(model_name="itemimage", name="size_bytes"),
        migrations.RemoveField(model_name="itemimage", name="source_format"),
        migrations.RemoveField(model_name="itemimage", name="uploaded_by"),
        migrations.RemoveField(model_name="itemimage", name="width"),
    ]
