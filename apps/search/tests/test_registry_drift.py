"""Guards against the registry, the builders and the dependency map drifting apart.

Nothing at runtime enforces either of these; a typo in a registry attribute is
a facet that is always empty, and a relation a builder reads without a
`DEPENDENCIES` entry is a document that keeps a stale value until a reindex.
"""

from django.db.models import Prefetch
import pytest

from apps.annotations.models import Graph, GraphComponent
from apps.annotations.tests.factories import GraphComponentFactory, GraphFactory
from apps.common.tests.factories import PlaceFactory
from apps.manuscripts.models import ImageText, MsDescArea
from apps.manuscripts.tests.factories import CatalogueNumberFactory, HistoricalItemDescriptionFactory, ItemImageFactory
from apps.scribes.tests.factories import HandDescriptionFactory, HandFactory, ScribeFactory
from apps.search.dependencies import DEPENDENCIES
from apps.search.registry import INDEX_REGISTRY, get_queryset_for_index
from apps.search.types import IndexType

PHYS_DESC = (
    '<physDesc><objectDesc form="codex"><supportDesc material="perg"/></objectDesc>'
    '<handDesc><handNote script="minusculeCaroline"/></handDesc>'
    '<decoDesc><decoNote type="border"/></decoDesc>'
    '<sealDesc><seal type="greatSeal"><material>wax</material></seal></sealDesc></physDesc>'
)
HISTORY = "<history><origin><origPlace><settlement>Durham</settlement></origPlace></origin></history>"


@pytest.fixture
def complete_corpus(db, settings):
    """One of everything, with every optional value set, so every attribute has a chance to appear."""
    settings.SEARCH_AUTO_REINDEX = False
    image = ItemImageFactory(locus="fol. 1r")
    image.tags = "damaged"
    image.save()
    part = image.item_part
    CatalogueNumberFactory(historical_item=part.historical_item)
    HistoricalItemDescriptionFactory(historical_item=part.historical_item)
    MsDescArea.objects.create(item_part=part, area="physDesc", is_published=True, content=PHYS_DESC)
    MsDescArea.objects.create(item_part=part, area="history", is_published=True, content=HISTORY)
    hand = HandFactory(item_part=part, place=PlaceFactory())
    HandDescriptionFactory(hand=hand, content="<p>a description</p>")
    hand.item_part_images.add(image)
    region = GraphFactory(item_image=image, hand=hand, allograph=None, annotation_type="text")
    glyph = GraphFactory(item_image=image, hand=hand, annotation_type="image")
    GraphComponentFactory(graph=glyph)
    ImageText.objects.create(
        item_image=image,
        type="Transcription",
        status="Live",
        language="la",
        content=(
            f'<p><seg type="address" corresp="#gid-{region.id}">Omnibus</seg> '
            '<persName type="name" ref="viaf:1">Will</persName> <placeName type="region">York</placeName></p>'
        ),
    )
    ScribeFactory(scriptorium="Durham")
    return image


@pytest.mark.django_db
@pytest.mark.parametrize("index_type", list(IndexType))
def test_every_registered_attribute_is_emitted_by_the_builder(index_type, complete_corpus):
    registration = INDEX_REGISTRY[index_type]
    emitted: set[str] = set()
    for obj in get_queryset_for_index(index_type):
        for document in registration.documents(obj):
            emitted |= set(document)
    declared = (
        set(registration.filterable_attributes)
        | set(registration.sortable_attributes)
        | set(registration.default_facet_attributes)
        | set(registration.searchable_attributes)
    )
    # Multi-valued attributes that only some rows carry (components, positions, tags …)
    # are fine to miss in a one-row corpus; a name that *no* builder path ever writes is not.
    writes = _attribute_names_written_by(registration)
    missing = {attr for attr in declared - emitted if attr not in writes}
    assert not missing, f"{index_type.segment}: registry names attributes the builder never emits: {sorted(missing)}"


def _attribute_names_written_by(registration) -> set[str]:
    """Every string literal used as a document key anywhere in the builder's module (and the shared context)."""
    import inspect
    import re

    import apps.search.documents.utils as utils

    builder_module = inspect.getmodule(registration.builder)
    assert builder_module is not None
    sources = [inspect.getsource(builder_module), inspect.getsource(utils)]
    # clauses/people/places are built through mentions.py and msdesc facets through msdesc_parser
    import apps.search.documents.mentions as mentions
    import apps.search.documents.msdesc_parser as msdesc

    sources += [inspect.getsource(mentions), inspect.getsource(msdesc)]
    return set(re.findall(r'"([a-z_]+)"', "\n".join(sources)))


@pytest.mark.django_db
@pytest.mark.parametrize("index_type", list(IndexType))
def test_every_model_a_builder_reads_is_in_the_dependency_map(index_type):
    """Each `select_related` / `prefetch_related` path ends on a model whose writes must reach this index."""
    registration = INDEX_REGISTRY[index_type]
    reached: set[type] = set()
    for path in (*registration.select_related, *registration.prefetch_related):
        lookup = path.prefetch_through if isinstance(path, Prefetch) else path
        model = registration.model
        for step in lookup.split("__"):
            # A reverse accessor (`graphcomponent_set`) is not a field name; the relation is.
            field = model._meta.get_field(step.removesuffix("_set"))
            model = field.related_model
            reached.add(model)
    # Through tables and the tag model carry no searchable values of their own; Graph and
    # GraphComponent have hand-written receivers in signals.py instead of a map entry.
    ignored = {m for m in reached if m._meta.auto_created or m.__name__.startswith("Tagulous_")}
    ignored |= {Graph, GraphComponent}
    missing = [
        m.__name__
        for m in reached - ignored
        if m not in DEPENDENCIES or index_type not in {i for dep in DEPENDENCIES[m] for i in dep.indexes}
    ]
    assert not missing, f"{index_type.segment} copies values from {missing}, which never invalidate it"
