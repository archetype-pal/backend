# Adds `AppSettings.is_public` (the enforced public/private visibility
# boundary described in apps.common.models.AppSettings — a public-facing
# view must filter on `is_public=True` rather than relying on a key-prefix
# convention) and seeds one `AppSettings` row per leaf site-features setting
# (key="site_features.<dotted.path>", e.g. "site_features.sections.search",
# is_public=True) with the current content of the frontend's
# config/site-features.json, the file this endpoint
# (apps.common.views.SiteFeaturesView) replaces.
#
# Mirrors config/site-features.json in the frontend repo as of this writing.
# Kept in sync manually with that file and with `DEFAULT_SITE_FEATURES` in
# apps/common/views.py, following the same pattern as `DEFAULT_LABELS` in
# 0008_sitelabel_per_key.py. `flatten_settings`/`unflatten_settings` are
# duplicated from `apps.common.views` rather than imported, per Django's
# "migrations should be self-contained" convention.
import json

from django.db import migrations, models

SITE_FEATURES_KEY = "site_features"
SITE_FEATURES_KEY_PREFIX = f"{SITE_FEATURES_KEY}."

DEFAULT_SITE_FEATURES = {
    "sections": {
        "search": True,
        "collection": True,
        "lightbox": True,
        "news": True,
        "blogs": True,
        "featureArticles": True,
        "events": True,
        "about": True,
    },
    "sectionOrder": [
        "search",
        "lightbox",
        "collection",
        "blogs",
        "featureArticles",
        "about",
        "news",
        "events",
    ],
    "features": {"manuscriptDescriptions": True},
    "searchCategories": {
        "manuscripts": {
            "enabled": True,
            "visibleColumns": [
                "Repository City",
                "Repository",
                "Shelfmark",
                "Catalogue Num.",
                "Text Date",
                "Doc. Type",
                "Images",
            ],
            "visibleFacets": [
                "image_availability",
                "text_date",
                "format",
                "type",
                "repository_city",
                "repository_name",
                "script",
                "material",
                "deco_type",
                "origin_place",
            ],
        },
        "images": {
            "enabled": True,
            "visibleColumns": [
                "Repository City",
                "Repository",
                "Shelfmark",
                "Doc. Type",
                "Thumbnail",
                "Annotations",
            ],
            "visibleFacets": [
                "text_date",
                "locus",
                "type",
                "repository_city",
                "repository_name",
                "features",
                "components",
                "component_features",
                "tags",
            ],
        },
        "scribes": {
            "enabled": True,
            "visibleColumns": ["Scribe Name", "Date", "Scriptorium"],
            "visibleFacets": ["text_date", "scriptorium"],
        },
        "hands": {
            "enabled": True,
            "visibleColumns": [
                "Hand Title",
                "Repository City",
                "Repository",
                "Shelfmark",
                "Place",
                "Date",
                "Catalogue Num.",
            ],
            "visibleFacets": ["text_date", "repository_name", "repository_city", "place"],
        },
        "graphs": {
            "enabled": True,
            "visibleColumns": [
                "Repository City",
                "Repository",
                "Shelfmark",
                "Document Date",
                "Allograph",
                "Character",
                "Hand Name",
                "Thumbnail",
            ],
            "visibleFacets": [
                "character",
                "character_type",
                "allograph",
                "place",
                "repository_name",
                "repository_city",
                "features",
                "components",
                "component_features",
                "positions",
            ],
        },
        "texts": {
            "enabled": True,
            "visibleColumns": ["Repository City", "Repository", "Shelfmark", "Text Type", "MS Date"],
            "visibleFacets": [
                "text_date",
                "text_type",
                "type",
                "repository_city",
                "repository_name",
                "status",
                "language",
                "places",
                "people",
            ],
        },
        "clauses": {
            "enabled": True,
            "visibleColumns": [
                "Cat. Num.",
                "Document Type",
                "Repository City",
                "Repository",
                "Shelfmark",
                "Text Date",
                "Text Type",
                "Clause Type",
            ],
            "visibleFacets": [
                "type",
                "repository_city",
                "repository_name",
                "text_date",
                "text_type",
                "clause_type",
                "status",
            ],
        },
        "people": {
            "enabled": True,
            "visibleColumns": [
                "Cat. Num.",
                "Document Type",
                "Repository City",
                "Repository",
                "Shelfmark",
                "Text Date",
                "Text Type",
                "Category",
            ],
            "visibleFacets": [
                "type",
                "repository_city",
                "repository_name",
                "text_date",
                "text_type",
                "person_type",
                "status",
            ],
        },
        "places": {
            "enabled": True,
            "visibleColumns": [
                "Cat. Num.",
                "Document Type",
                "Repository City",
                "Repository",
                "Shelfmark",
                "Text Date",
                "Text Type",
                "Place Type",
            ],
            "visibleFacets": [
                "type",
                "repository_city",
                "repository_name",
                "text_date",
                "text_type",
                "place_type",
                "status",
            ],
        },
    },
}


def flatten_settings(obj, prefix=""):
    flat = {}
    for sub_key, sub_value in obj.items():
        dotted_key = f"{prefix}.{sub_key}" if prefix else sub_key
        if isinstance(sub_value, dict):
            flat.update(flatten_settings(sub_value, dotted_key))
        else:
            flat[dotted_key] = sub_value
    return flat


def seed_site_features(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")

    for dotted_key, value in flatten_settings(DEFAULT_SITE_FEATURES).items():
        AppSettings.objects.get_or_create(
            key=f"{SITE_FEATURES_KEY_PREFIX}{dotted_key}",
            defaults={
                "value": json.dumps(value),
                "description": f"Site feature setting '{dotted_key}' (public site-features config).",
                "is_public": True,
            },
        )


def unseed_site_features(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")
    AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0009_appsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="is_public",
            field=models.BooleanField(
                default=False, help_text="Whether this key may be served by an unauthenticated/public endpoint."
            ),
        ),
        migrations.RunPython(seed_site_features, unseed_site_features),
    ]
