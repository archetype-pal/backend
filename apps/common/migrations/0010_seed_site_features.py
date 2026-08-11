# Data migration (no schema change): seeds the `site_features` AppSettings
# row with the current content of the frontend's config/site-features.json,
# the file this endpoint (apps.common.views.SiteFeaturesView) replaces.
#
# Mirrors config/site-features.json in the frontend repo as of this writing.
# Kept in sync manually with that file and with `DEFAULT_SITE_FEATURES` in
# apps/common/views.py, following the same pattern as `DEFAULT_LABELS` in
# 0008_sitelabel_per_key.py.
import json

from django.db import migrations

SITE_FEATURES_KEY = "site_features"

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


def seed_site_features(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")

    AppSettings.objects.get_or_create(
        key=SITE_FEATURES_KEY,
        defaults={
            "value": json.dumps(DEFAULT_SITE_FEATURES),
            "description": (
                "Public site-features configuration blob (section visibility, section order, "
                "and per-search-category column/facet visibility) served to the frontend in "
                "place of the old config/site-features.json file."
            ),
        },
    )


def unseed_site_features(apps, schema_editor):
    AppSettings = apps.get_model("common", "AppSettings")
    AppSettings.objects.filter(key=SITE_FEATURES_KEY).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0009_appsettings"),
    ]

    operations = [
        migrations.RunPython(seed_site_features, unseed_site_features),
    ]
