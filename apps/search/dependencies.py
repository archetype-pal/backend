"""Which search documents a model write invalidates.

Meilisearch cannot join, so every document copies the related values it needs to
be shown, filtered and faceted — a graph document carries its hand's name, its
scribe's name and its repository. Refreshing only the row's own document would
therefore leave the Hands tab renamed and the Graphs tab still showing the old
name.

`signals.py` registers a pair of receivers per entry; `registry.py` stays the
source of truth for the indexes themselves.

Every model whose values a document copies has an entry, so an editor never has
to know which backoffice page reaches search. Blast radius is not a reason to
leave one out: a chunked sync rebuilds fewer documents than the full reindex it
would otherwise need.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from django.db import models

from apps.annotations.models import Graph
from apps.common.models import Date, Place
from apps.manuscripts.models import (
    BibliographicSource,
    CatalogueNumber,
    CurrentItem,
    HistoricalItem,
    ImageText,
    ItemFormat,
    ItemImage,
    ItemPart,
    MsDescArea,
    Repository,
)
from apps.scribes.models import Hand, HandDescription, Scribe
from apps.search.types import IndexType
from apps.symbols_structure.models import Allograph, Character, Component, Feature, Position

# All built from ImageText, so one write invalidates the same rows in each.
TEXT_INDEXES = (IndexType.TEXTS, IndexType.CLAUSES, IndexType.PEOPLE, IndexType.PLACES)


@dataclass(frozen=True)
class IndexDependency:
    """Indexes a write invalidates, and which of their source rows to rebuild.

    `resolve` returns source-model pks, which for a fan-out index means the
    parent row rather than the documents. Querysets stay unevaluated so the
    caller can stream them.
    """

    indexes: tuple[IndexType, ...]
    resolve: Callable[[models.Model], Iterable[int]]


Resolver = Callable[[models.Model], Iterable[int]]


def _attr(name: str) -> Resolver:
    """The row's own pk, or a foreign key it carries (None when unset).

    `is not None`, not truthiness: whether a row belongs in an index is the
    registration's `queryset_filter` to decide, not a resolver's.
    """
    return lambda instance: [value] if (value := getattr(instance, name, None)) is not None else []


def _rows(manager: Any, lookup: str) -> Resolver:
    """Ids of `manager`'s rows whose `lookup` points at the written row (distinct: a join can repeat a row)."""
    return lambda instance: manager.filter(**{lookup: instance.pk}).values_list("id", flat=True).distinct()


def _manuscript_spine(part_lookup: str, *, hands: bool = True) -> tuple[IndexDependency, ...]:
    """Every document under the manuscripts reached by one lookup on `ItemPart`.

    A manuscript's historical item, current item, repository and date all reach
    the same rows, differing only in how they filter `ItemPart`. Hand documents
    carry their own date rather than the manuscript's, so a Date write leaves
    them out (`hands=False`).
    """
    return (
        IndexDependency((IndexType.ITEM_PARTS,), _rows(ItemPart.objects, part_lookup)),
        IndexDependency((IndexType.ITEM_IMAGES,), _rows(ItemImage.objects, f"item_part__{part_lookup}")),
        *((IndexDependency((IndexType.HANDS,), _rows(Hand.objects, f"item_part__{part_lookup}")),) if hands else ()),
        IndexDependency((IndexType.GRAPHS,), _rows(Graph.all_objects, f"item_image__item_part__{part_lookup}")),
        IndexDependency(TEXT_INDEXES, _rows(ImageText.objects, f"item_image__item_part__{part_lookup}")),
    )


def _annotation_taxonomy(graph_lookup: str) -> tuple[IndexDependency, ...]:
    """Annotation documents naming a symbol, and the image documents that summarise the same symbols."""
    return (
        IndexDependency((IndexType.GRAPHS,), _rows(Graph.all_objects, graph_lookup)),
        IndexDependency((IndexType.ITEM_IMAGES,), _rows(ItemImage.objects, f"graphs__{graph_lookup}")),
    )


def _catalogue_described(part_lookup: str) -> tuple[IndexDependency, ...]:
    """Documents printing a manuscript's catalogue numbers (graph and image documents do not)."""
    return (
        IndexDependency((IndexType.ITEM_PARTS,), _rows(ItemPart.objects, part_lookup)),
        IndexDependency((IndexType.HANDS,), _rows(Hand.objects, f"item_part__{part_lookup}")),
        IndexDependency(TEXT_INDEXES, _rows(ImageText.objects, f"item_image__item_part__{part_lookup}")),
    )


# Graph and GraphComponent are absent on purpose: one graph write fans out into
# many component writes in the same request, which needs the coalescing their
# receivers in `signals.py` already do.
DEPENDENCIES: dict[type[models.Model], tuple[IndexDependency, ...]] = {
    ItemImage: (
        IndexDependency((IndexType.ITEM_IMAGES,), _attr("pk")),
        # An item-part document counts its images, so adding or removing one changes it.
        IndexDependency((IndexType.ITEM_PARTS,), _attr("item_part_id")),
        IndexDependency((IndexType.GRAPHS,), _rows(Graph.all_objects, "item_image_id")),
        IndexDependency(TEXT_INDEXES, _rows(ImageText.objects, "item_image_id")),
    ),
    ImageText: (
        IndexDependency((IndexType.TEXTS, IndexType.PEOPLE, IndexType.PLACES), _attr("pk")),
        # Clause documents borrow annotation ids from the image's other text, so editing one side rebuilds both.
        IndexDependency(
            (IndexType.CLAUSES,),
            lambda o: ImageText.objects.filter(item_image_id=o.item_image_id).values_list("id", flat=True),
        ),
    ),
    Hand: (
        IndexDependency((IndexType.HANDS,), _attr("pk")),
        IndexDependency((IndexType.GRAPHS,), _rows(Graph.all_objects, "hand_id")),
    ),
    # Edited through their own endpoint, so a Hand save never reindexes them.
    HandDescription: (IndexDependency((IndexType.HANDS,), _attr("hand_id")),),
    Place: (
        IndexDependency((IndexType.HANDS,), _rows(Hand.objects, "place_id")),
        IndexDependency((IndexType.GRAPHS,), _rows(Graph.all_objects, "hand__place_id")),
    ),
    Scribe: (
        IndexDependency((IndexType.SCRIBES,), _attr("pk")),
        IndexDependency((IndexType.GRAPHS,), _rows(Graph.all_objects, "hand__scribe_id")),
    ),
    ItemPart: (
        IndexDependency((IndexType.ITEM_PARTS,), _attr("pk")),
        IndexDependency((IndexType.ITEM_IMAGES,), _rows(ItemImage.objects, "item_part_id")),
        IndexDependency((IndexType.HANDS,), _rows(Hand.objects, "item_part_id")),
        IndexDependency((IndexType.GRAPHS,), _rows(Graph.all_objects, "item_image__item_part_id")),
        IndexDependency(TEXT_INDEXES, _rows(ImageText.objects, "item_image__item_part_id")),
    ),
    MsDescArea: (IndexDependency((IndexType.ITEM_PARTS,), _attr("item_part_id")),),
    HistoricalItem: _manuscript_spine("historical_item_id"),
    CurrentItem: _manuscript_spine("current_item_id"),
    Repository: _manuscript_spine("current_item__repository_id"),
    Date: (
        *_manuscript_spine("historical_item__date_id", hands=False),
        # A hand document carries its *own* date, and the scribe document its period.
        IndexDependency((IndexType.HANDS,), _rows(Hand.objects, "date_id")),
        IndexDependency((IndexType.SCRIBES,), _rows(Scribe.objects, "period_id")),
    ),
    Allograph: _annotation_taxonomy("allograph_id"),
    Character: _annotation_taxonomy("allograph__character_id"),
    Component: _annotation_taxonomy("components__id"),
    Feature: _annotation_taxonomy("graphcomponent__features__id"),
    Position: _annotation_taxonomy("positions__id"),
    CatalogueNumber: _catalogue_described("historical_item__catalogue_numbers__id"),
    BibliographicSource: _catalogue_described("historical_item__catalogue_numbers__catalogue_id"),
    ItemFormat: (IndexDependency((IndexType.ITEM_PARTS,), _rows(ItemPart.objects, "historical_item__format_id")),),
}
