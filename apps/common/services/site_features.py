"""The public site-features configuration, stored one `AppSettings` row per leaf.

Replaces the frontend's old `config/site-features.json`. Keys are dotted paths
(`site_features.theme.primaryColor`), values JSON-encoded, so the frontend's
nested document is flattened on write and rebuilt on read.
"""

import json
from typing import Any

from django.db import transaction

from apps.common.audit import audit_actor
from apps.common.models import AppSettings

SITE_FEATURES_KEY = "site_features"
SITE_FEATURES_KEY_PREFIX = f"{SITE_FEATURES_KEY}."


def flatten_settings(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested dict into {dotted.path: leaf_value}.

    Lists (and other non-dict values) are leaves, not further split: a row
    per *setting*, not a row per list item — `sectionOrder` or
    `visibleColumns` are each one setting whose value happens to be a list.
    """
    flat: dict[str, Any] = {}
    for sub_key, sub_value in obj.items():
        dotted_key = f"{prefix}.{sub_key}" if prefix else sub_key
        if isinstance(sub_value, dict):
            flat.update(flatten_settings(sub_value, dotted_key))
        else:
            flat[dotted_key] = sub_value
    return flat


def unflatten_settings(flat: dict[str, Any]) -> dict[str, Any]:
    """Inverse of `flatten_settings`: rebuild a nested dict from dotted keys.

    A row whose key collides with another row's prefix (e.g. both `sections`
    and `sections.search`) is malformed — created by a bug or by hand, since
    `flatten_settings` never produces that pairing itself. Skip it rather than
    crash, consistent with this view never 500ing on corrupt settings data.
    """
    nested: dict[str, Any] = {}
    # Deepest keys first: a proper prefix always has fewer dots, so it is
    # consumed after the subtree it collides with and the leaf guard drops it.
    for dotted_key, value in sorted(flat.items(), key=lambda kv: kv[0].count("."), reverse=True):
        *parents, leaf = dotted_key.split(".")
        node = nested
        for part in parents:
            node = node.setdefault(part, {})
        if not isinstance(node.get(leaf), dict):
            node[leaf] = value
    return nested


# Mirrors config/site-features.json in the frontend repo. Kept in sync
# manually with that file and with the seed data in
# 0010_seed_site_features.py — there are three of these because the frontend
# needs its own same-process default, the migration needs a self-contained
# one-time seed value, and this one is the last-resort fallback so `GET` never
# 500s even if every `AppSettings` row for this key is missing, deactivated,
# or corrupt.
DEFAULT_SITE_FEATURES: dict[str, Any] = {
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
    # The brand colours the backoffice "UI customization" panel edits — the
    # MoA blue/amber this app shipped with before any deployment or admin
    # could change it. `primaryColor`/`ring` cover the header, primary
    # buttons, and active nav; `primaryForegroundColor` is drawn on top of
    # them; `accentColor` is the secondary/highlight colour. The four
    # `titleBar`/`navBar` colours let the two rows of the site header be
    # repainted independently (archetype-pal/frontend#103); they default to
    # the same primary/foreground pair, matching the single-colour header
    # this app rendered before the rows could be repainted separately.
    "theme": {
        "primaryColor": "#075783",
        "primaryForegroundColor": "#faf8f5",
        "accentColor": "#f59f0a",
        "titleBarBackgroundColor": "#075783",
        "titleBarTextColor": "#faf8f5",
        "navBarBackgroundColor": "#075783",
        "navBarTextColor": "#faf8f5",
    },
    # The instance logo shown at the top of the header's title row. Empty
    # until an admin sets one, matching the site-title-only header this app
    # renders today.
    "branding": {"logoUrl": ""},
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
                "seal_type",
                "seal_material",
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


def _stored_rows():
    # `is_public=True` is the enforced boundary (see AppSettings docstring) —
    # the key prefix narrows to *which* settings this store owns, `is_public`
    # is what makes them safe to serve to an anonymous caller. A row under this
    # prefix that isn't flagged public (created by a bug, or by hand) is
    # silently excluded rather than served.
    return AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX, is_active=True, is_public=True)


def get_site_features() -> dict[str, Any]:
    """The nested site-features document, or the defaults when nothing usable is stored."""
    flat: dict[str, Any] = {}
    for row in _stored_rows():
        try:
            flat[row.key[len(SITE_FEATURES_KEY_PREFIX) :]] = json.loads(row.value)
        except (TypeError, ValueError):  # fmt: skip
            continue  # never 500 on a corrupt row
    return unflatten_settings(flat) if flat else DEFAULT_SITE_FEATURES


def replace_site_features(features: dict[str, Any], *, actor) -> dict[str, Any]:
    """Full replace: every stored key absent from `features` is deleted. Returns the stored document."""
    flat = flatten_settings(features)
    keys = {f"{SITE_FEATURES_KEY_PREFIX}{dotted_key}" for dotted_key in flat}

    with transaction.atomic(), audit_actor(actor):
        AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX).exclude(key__in=keys).delete()
        stored = dict(_stored_rows().values_list("key", "value"))
        for dotted_key, value in flat.items():
            key = f"{SITE_FEATURES_KEY_PREFIX}{dotted_key}"
            encoded = json.dumps(value)
            if stored.get(key) == encoded:
                continue  # every save emits an EditEvent; don't audit no-op writes
            AppSettings.objects.update_or_create(
                key=key,
                defaults={
                    "value": encoded,
                    "description": f"Site feature setting '{dotted_key}' (public site-features config).",
                    "is_active": True,
                    "is_public": True,
                },
            )
    return get_site_features()
