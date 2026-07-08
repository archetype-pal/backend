import json

from django.conf import settings
from django.db import migrations


def seed_labels(apps, schema_editor):
    SiteLabels = apps.get_model("common", "SiteLabels")
    if SiteLabels.objects.filter(pk=1).exists():
        return

    # One-time import of the frontend's file-based config, so existing
    # customizations survive the move to the database.
    json_path = settings.BASE_DIR.parent / "archetype3-frontend" / "config" / "model-labels.json"
    labels = {}
    try:
        with open(json_path, encoding="utf-8") as file:
            raw = json.load(file)
        if isinstance(raw, dict) and isinstance(raw.get("labels"), dict):
            labels = raw["labels"]
    except (OSError, json.JSONDecodeError):
        labels = {}

    SiteLabels.objects.create(pk=1, labels=labels)


def unseed_labels(apps, schema_editor):
    SiteLabels = apps.get_model("common", "SiteLabels")
    SiteLabels.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("common", "0008_sitelabels"),
    ]

    operations = [
        migrations.RunPython(seed_labels, unseed_labels),
    ]
