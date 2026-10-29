"""The `elementid` selector → in-text link embedding, and the 0027 data migration that runs it.

A DigiPal corpus carries no ``data-graph-id`` at all; the linkage lives only as
the legacy ``elementid`` tuple on the Graph. The migration is what puts it back.
"""

from django.apps import apps as app_registry
import pytest

from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei.elementid import ElementSpec, embed_annotation_ids_in_content, parse_elementid
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.search.documents.clauses import build_clause_documents


def test_parse_elementid_extracts_tag_type_and_text_hint():
    spec = parse_elementid('[["", "clause"], ["type", "salutation"], ["@text", "salutem"]]')
    assert spec == ElementSpec(tag="clause", type_name="salutation", text_hint="salutem")


def test_embedding_merges_into_an_existing_link_list_and_annotates_every_match():
    content = (
        '<p><span data-dpt="clause" data-dpt-type="address">Alpha</span>'
        '<span data-dpt="clause" data-dpt-type="address" data-graph-id="10">Beta</span></p>'
    )
    spec = ElementSpec(tag="clause", type_name="address", text_hint=None)

    new_content, matched, changed = embed_annotation_ids_in_content(content, spec, annotation_id=11)

    assert (matched, changed) == (2, 2)
    assert 'data-graph-id="11"' in new_content
    assert 'data-graph-id="10,11"' in new_content


def test_embedding_respects_the_text_hint():
    content = '<p><span data-dpt="person" data-dpt-type="name">David</span></p>'
    spec = ElementSpec(tag="person", type_name="name", text_hint="William")

    assert embed_annotation_ids_in_content(content, spec, annotation_id=99) == (content, 0, 0)


def _run_migration():
    from importlib import import_module

    module = import_module("apps.manuscripts.migrations.0027_embed_text_region_links")
    module.embed_text_region_links(app_registry, None)


TRANSCRIPTION = (
    '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="intitulatio">Alexander Rex</span> '
    '<span data-dpt="clause" data-dpt-cat="words" data-dpt-type="salutation">Salutem</span></p>'
)
TRANSLATION = (
    '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="intitulatio">Alexander king</span> '
    '<span data-dpt="clause" data-dpt-cat="words" data-dpt-type="salutation">greeting</span></p>'
)


def _prod_shaped_image():
    """An image whose texts have clause markup but no region links."""
    image = ItemImageFactory()
    transcription = ImageTextFactory(item_image=image, content=TRANSCRIPTION, type=ImageText.Type.TRANSCRIPTION)
    translation = ImageTextFactory(item_image=image, content=TRANSLATION, type=ImageText.Type.TRANSLATION)
    graph = GraphFactory(
        item_image=image,
        annotation={
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
            "properties": {"elementid": [["", "clause"], ["type", "salutation"]]},
        },
    )
    # A graph with no elementid must be skipped, not crash the migration.
    GraphFactory(item_image=image, annotation={"type": "Feature", "properties": {}})
    return image, transcription, translation, graph


@pytest.mark.django_db
def test_migration_embeds_links_from_the_graph_elementid():
    _image, transcription, translation, graph = _prod_shaped_image()
    assert "data-graph-id" not in transcription.content

    _run_migration()

    transcription.refresh_from_db()
    translation.refresh_from_db()
    # The salutation clause is linked on *both* sides of the pair; the
    # intitulatio, which no graph claims, is left alone.
    assert f'data-graph-id="{graph.id}"' in transcription.content
    assert f'data-graph-id="{graph.id}"' in translation.content
    assert transcription.content.count("data-graph-id") == 1


@pytest.mark.django_db
def test_migration_is_idempotent():
    _image, transcription, _translation, _graph = _prod_shaped_image()

    _run_migration()
    once = ImageText.objects.get(pk=transcription.pk).content
    _run_migration()

    assert ImageText.objects.get(pk=transcription.pk).content == once


@pytest.mark.django_db
def test_clauses_index_gains_regions_after_the_migration():
    _image, transcription, _translation, graph = _prod_shaped_image()

    before = build_clause_documents(ImageText.objects.get(pk=transcription.pk))
    _run_migration()
    after = build_clause_documents(ImageText.objects.get(pk=transcription.pk))

    # Both clauses are indexed either way — that is the builder fix — but only
    # after the migration does one of them carry a region to crop.
    assert [d["annotation_id"] for d in before] == [None, None]
    assert [d["annotation_id"] for d in after] == [None, graph.id]
