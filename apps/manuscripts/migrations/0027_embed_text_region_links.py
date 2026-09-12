"""Embed the text↔region links that the MoA corpus was migrated without.

A clause is linked to its image region by a ``data-graph-id`` attribute on the
span (``corresp`` once the row is TEI). The DigiPal import never wrote those:
it left the linkage on the *Graph* side only, as a legacy
``annotation.properties.elementid`` tuple like ``[["", "clause"], ["type",
"address"]]``. `embed_annotation_ids --from-graphs` resolves those tuples back
into the text, and `docs/tei.md` §5.3 runs it as step 2b when migrating a
backup — but the production database predates that procedure, so its texts
carry no links at all.

That is invisible until something requires a region. The clauses index did,
briefly, and the category emptied. This repairs the data rather than leaving
every consumer to cope with its absence.

Additive and idempotent: it only ever adds an id to a span that lacks it, so a
re-run is a no-op, and so is a corpus that already has its links (including any
already converted to TEI, whose ``corresp`` refs this deliberately does not
touch).
"""

import json

from django.db import migrations

# Historical models carry no enum; these are `ImageText.Type` values.
_LINKABLE_TEXT_TYPES = ("Transcription", "Translation")


def embed_text_region_links(apps, schema_editor):
    # Imported lazily: the command module pulls in real (non-historical) models
    # at import time, which must not happen while the migration graph is built.
    from apps.manuscripts.management.commands.embed_annotation_ids import (
        embed_annotation_ids_in_content,
        parse_elementid,
    )

    Graph = apps.get_model("annotations", "Graph")
    ImageText = apps.get_model("manuscripts", "ImageText")

    graphs = (
        Graph.objects.exclude(annotation__properties__elementid=None)
        .only("id", "annotation", "item_image_id")
        .order_by("id")
    )

    # One pass over the texts, held in memory by id: a graph's spec can match
    # both texts of its image, and several graphs match the same text.
    pending: dict[int, str] = {}
    texts_by_image: dict[int, list] = {}
    for text in ImageText.objects.filter(type__in=_LINKABLE_TEXT_TYPES).only("id", "content", "item_image_id"):
        if text.content:
            texts_by_image.setdefault(text.item_image_id, []).append(text)

    for graph in graphs.iterator(chunk_size=500):
        elementid = ((graph.annotation or {}).get("properties") or {}).get("elementid")
        if not elementid:
            continue
        try:
            spec = parse_elementid(json.dumps(elementid))
        except ValueError:
            continue
        for text in texts_by_image.get(graph.item_image_id, ()):
            content = pending.get(text.id, text.content)
            new_content, _matched, changed = embed_annotation_ids_in_content(content, spec, graph.id)
            if changed:
                pending[text.id] = new_content

    for text_id, content in pending.items():
        ImageText.objects.filter(pk=text_id).update(content=content)


class Migration(migrations.Migration):
    dependencies = [
        ("manuscripts", "0026_alter_historicalitemdescription_content"),
        ("annotations", "0011_alter_graph_options_alter_graph_managers"),
    ]

    operations = [
        migrations.RunPython(embed_text_region_links, migrations.RunPython.noop),
    ]
