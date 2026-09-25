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
from typing import Any, cast

from django.db import models
from django.db.models import QuerySet

from apps.annotations.models import Graph
from apps.common.models import Date
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
from apps.scribes.models import Hand, Scribe
from apps.search.types import IndexType
from apps.symbols_structure.models import Allograph, Character, Component, Feature, Position

# All built from ImageText, so one write invalidates the same rows in each.
TEXT_INDEXES = (IndexType.TEXTS, IndexType.CLAUSES, IndexType.PEOPLE, IndexType.PLACES)


@dataclass(frozen=True)
class IndexDependency:
    """Indexes a write invalidates, and which of their source rows to rebuild.

    `resolve` returns source-model pks, which for a fan-out index means the
    parent row rather than the documents. Return a queryset: the caller streams
    it with `.iterator()`.
    """

    indexes: tuple[IndexType, ...]
    resolve: Callable[[models.Model], Iterable[int]]


def _one(value: int | None) -> list[int]:
    # `is not None`, not truthiness: whether a row belongs in an index is the
    # registration's `queryset_filter` to decide, not a resolver's.
    return [value] if value is not None else []


def _ids(queryset: QuerySet[Any]) -> Iterable[int]:
    """Row ids, unevaluated so the caller can stream them."""
    return cast(Iterable[int], queryset.values_list("id", flat=True))


def _distinct_ids(queryset: QuerySet[Any]) -> Iterable[int]:
    """Row ids from a many-to-many join, which can repeat a row."""
    return cast(Iterable[int], queryset.values_list("id", flat=True).distinct())


def _own_pk(instance: models.Model) -> Iterable[int]:
    return _one(instance.pk)


def _parent_item_part(instance: models.Model) -> Iterable[int]:
    # An item-part document counts its images, so adding or removing one
    # changes the manuscript's own document.
    return _one(getattr(instance, "item_part_id", None))


def _graphs_on_image(instance: models.Model) -> Iterable[int]:
    return _ids(Graph.all_objects.filter(item_image_id=instance.pk))


def _texts_on_image(instance: models.Model) -> Iterable[int]:
    return _ids(ImageText.objects.filter(item_image_id=instance.pk))


def _texts_sharing_image(instance: models.Model) -> Iterable[int]:
    # Clause documents borrow annotation ids from the image's other text, so
    # editing one side rebuilds both.
    return _ids(ImageText.objects.filter(item_image_id=getattr(instance, "item_image_id", None)))


def _graphs_of_hand(instance: models.Model) -> Iterable[int]:
    return _ids(Graph.all_objects.filter(hand_id=instance.pk))


def _graphs_of_scribe(instance: models.Model) -> Iterable[int]:
    return _ids(Graph.all_objects.filter(hand__scribe_id=instance.pk))


def _images_of_part(instance: models.Model) -> Iterable[int]:
    return _ids(ItemImage.objects.filter(item_part_id=instance.pk))


def _hands_of_part(instance: models.Model) -> Iterable[int]:
    return _ids(Hand.objects.filter(item_part_id=instance.pk))


def _graphs_under_part(instance: models.Model) -> Iterable[int]:
    return _ids(Graph.all_objects.filter(item_image__item_part_id=instance.pk))


def _texts_under_part(instance: models.Model) -> Iterable[int]:
    return _ids(ImageText.objects.filter(item_image__item_part_id=instance.pk))


def _hands_dated(instance: models.Model) -> Iterable[int]:
    # A hand document carries its *own* date, not its manuscript's.
    return _ids(Hand.objects.filter(date_id=instance.pk))


def _scribes_dated(instance: models.Model) -> Iterable[int]:
    # `Scribe.period` is a Date too, and the scribe document prints it.
    return _ids(Scribe.objects.filter(period_id=instance.pk))


def _manuscript_spine(part_lookup: str) -> tuple[IndexDependency, ...]:
    """Documents under the manuscripts reached by one lookup on `ItemPart`.

    A manuscript's historical item, current item, repository and date all reach
    the same rows, differing only in how they filter `ItemPart`.

    `hands` is excluded because which of them a hand document depends on varies;
    callers add it.
    """
    image_lookup = f"item_part__{part_lookup}"
    deep_lookup = f"item_image__item_part__{part_lookup}"
    return (
        IndexDependency((IndexType.ITEM_PARTS,), lambda o: _ids(ItemPart.objects.filter(**{part_lookup: o.pk}))),
        IndexDependency((IndexType.ITEM_IMAGES,), lambda o: _ids(ItemImage.objects.filter(**{image_lookup: o.pk}))),
        IndexDependency((IndexType.GRAPHS,), lambda o: _ids(Graph.all_objects.filter(**{deep_lookup: o.pk}))),
        IndexDependency(TEXT_INDEXES, lambda o: _ids(ImageText.objects.filter(**{deep_lookup: o.pk}))),
    )


def _hands_under(part_lookup: str) -> IndexDependency:
    lookup = f"item_part__{part_lookup}"
    return IndexDependency((IndexType.HANDS,), lambda o: _ids(Hand.objects.filter(**{lookup: o.pk})))


def _annotation_taxonomy(graph_lookup: str) -> tuple[IndexDependency, ...]:
    """Annotation documents naming a symbol, and the image documents that
    summarise the same symbols across their graphs.
    """
    image_lookup = f"graphs__{graph_lookup}"
    return (
        IndexDependency((IndexType.GRAPHS,), lambda o: _distinct_ids(Graph.all_objects.filter(**{graph_lookup: o.pk}))),
        IndexDependency(
            (IndexType.ITEM_IMAGES,), lambda o: _distinct_ids(ItemImage.objects.filter(**{image_lookup: o.pk}))
        ),
    )


def _catalogue_described(part_lookup: str) -> tuple[IndexDependency, ...]:
    """Documents printing a manuscript's catalogue numbers.

    Graph and image documents are not among them, so this is narrower than
    `_manuscript_spine`.
    """
    hand_lookup = f"item_part__{part_lookup}"
    text_lookup = f"item_image__item_part__{part_lookup}"
    return (
        IndexDependency(
            (IndexType.ITEM_PARTS,), lambda o: _distinct_ids(ItemPart.objects.filter(**{part_lookup: o.pk}))
        ),
        IndexDependency((IndexType.HANDS,), lambda o: _distinct_ids(Hand.objects.filter(**{hand_lookup: o.pk}))),
        IndexDependency(TEXT_INDEXES, lambda o: _distinct_ids(ImageText.objects.filter(**{text_lookup: o.pk}))),
    )


# Graph and GraphComponent are absent on purpose: one graph write fans out into
# many component writes in the same request, which needs the coalescing their
# receivers in `signals.py` already do.
DEPENDENCIES: dict[type[models.Model], tuple[IndexDependency, ...]] = {
    ItemImage: (
        IndexDependency((IndexType.ITEM_IMAGES,), _own_pk),
        IndexDependency((IndexType.ITEM_PARTS,), _parent_item_part),
        IndexDependency((IndexType.GRAPHS,), _graphs_on_image),
        IndexDependency(TEXT_INDEXES, _texts_on_image),
    ),
    ImageText: (
        IndexDependency((IndexType.TEXTS, IndexType.PEOPLE, IndexType.PLACES), _own_pk),
        IndexDependency((IndexType.CLAUSES,), _texts_sharing_image),
    ),
    Hand: (
        IndexDependency((IndexType.HANDS,), _own_pk),
        IndexDependency((IndexType.GRAPHS,), _graphs_of_hand),
    ),
    Scribe: (
        IndexDependency((IndexType.SCRIBES,), _own_pk),
        IndexDependency((IndexType.GRAPHS,), _graphs_of_scribe),
    ),
    ItemPart: (
        IndexDependency((IndexType.ITEM_PARTS,), _own_pk),
        IndexDependency((IndexType.ITEM_IMAGES,), _images_of_part),
        IndexDependency((IndexType.HANDS,), _hands_of_part),
        IndexDependency((IndexType.GRAPHS,), _graphs_under_part),
        IndexDependency(TEXT_INDEXES, _texts_under_part),
    ),
    MsDescArea: (IndexDependency((IndexType.ITEM_PARTS,), _parent_item_part),),
    HistoricalItem: (
        *_manuscript_spine("historical_item_id"),
        _hands_under("historical_item_id"),
    ),
    CurrentItem: (
        *_manuscript_spine("current_item_id"),
        _hands_under("current_item_id"),
    ),
    Repository: (
        *_manuscript_spine("current_item__repository_id"),
        _hands_under("current_item__repository_id"),
    ),
    Date: (
        *_manuscript_spine("historical_item__date_id"),
        IndexDependency((IndexType.HANDS,), _hands_dated),
        IndexDependency((IndexType.SCRIBES,), _scribes_dated),
    ),
    Allograph: _annotation_taxonomy("allograph_id"),
    Character: _annotation_taxonomy("allograph__character_id"),
    Component: _annotation_taxonomy("components__id"),
    Feature: _annotation_taxonomy("graphcomponent__features__id"),
    Position: _annotation_taxonomy("positions__id"),
    CatalogueNumber: _catalogue_described("historical_item__catalogue_numbers__id"),
    BibliographicSource: _catalogue_described("historical_item__catalogue_numbers__catalogue_id"),
    ItemFormat: (
        IndexDependency(
            (IndexType.ITEM_PARTS,), lambda o: _ids(ItemPart.objects.filter(historical_item__format_id=o.pk))
        ),
    ),
}
