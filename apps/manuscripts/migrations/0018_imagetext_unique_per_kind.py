from django.db import migrations, models


def _dedupe_image_texts(apps, schema_editor):
    """Keep the most-recently-modified row per (item_image, type); drop the rest.

    The user's domain has at most one of each kind per image. The dedupe is
    defensive: it ensures the unique constraint can be added cleanly even on
    legacy datasets where stray duplicates might exist.
    """
    ImageText = apps.get_model("manuscripts", "ImageText")
    seen: dict[tuple[int, str], int] = {}
    to_delete: list[int] = []
    # Iterate newest-first so the first sighting per (item_image, type) wins.
    for row in ImageText.objects.order_by("-modified", "-id").values("id", "item_image_id", "type"):
        key = (row["item_image_id"], row["type"])
        if key in seen:
            to_delete.append(row["id"])
        else:
            seen[key] = row["id"]
    if to_delete:
        ImageText.objects.filter(id__in=to_delete).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0017_tagulous_itemimage_tags_itemimage_tags"),
    ]

    operations = [
        migrations.RunPython(_dedupe_image_texts, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="imagetext",
            constraint=models.UniqueConstraint(
                fields=("item_image", "type"),
                name="imagetext_one_per_kind_per_image",
            ),
        ),
    ]
