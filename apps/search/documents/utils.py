import json
import re

from apps.annotations.models import Graph
from apps.common.text import collapse_whitespace


def get_attr(obj, path: str):
    """Follow relation path (e.g. ``item_part__current_item__shelfmark``) and return value or None."""
    for part in path.split("__"):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return str(obj)


def strip_html_for_search(html_content: str) -> str:
    """Meilisearch doesn't split tokens on ``<``/``>``, so markup must go before indexing."""
    text = re.sub(r"<[^>]+>", " ", html_content)
    return collapse_whitespace(text)


def display_label(item_part) -> str | None:
    """`ItemPart.display_label()`, stripped; None when the part is missing or the label is blank."""
    value = getattr(item_part, "display_label", None)
    if callable(value):
        value = value()
    if value is None:
        return None
    return str(value).strip() or None


def date_fields(date) -> dict:
    """The `date` / `date_min` / `date_max` triple for a `common.Date` (all None when unset).

    `date_min`/`date_max` are set directly rather than via `get_attr()`, which
    stringifies — they are sorted and range-filtered numerically.
    """
    if date is None:
        return {"date": None, "date_min": None, "date_max": None}
    return {"date": date.date, "date_min": date.min_weight, "date_max": date.max_weight}


_DIGIT_RUN = re.compile(r"\d+")


def natural_sort_key(value: str | None) -> str | None:
    """A string that sorts shelfmarks the way a reader expects: `MS 2` before `MS 10`.

    Every run of digits is left-padded to a fixed width and the rest lower-cased,
    so a plain string comparison (which is all Meilisearch's sort does) orders
    numbers numerically. None stays None so `drop_none` leaves the key out.
    """
    if value is None:
        return None
    return _DIGIT_RUN.sub(lambda match: match.group(0).zfill(8), value).casefold()


def manuscript_context(item_part) -> dict:
    """The manuscript fields every document copies from its ItemPart.

    Repository name/city and shelfmark come from the current item, the type
    and date triple from the historical item. All None when `item_part` is
    None, so callers can `drop_none` uniformly. `shelfmark_sort` is the
    natural-order key the registry's sort alias points `shelfmark` at.
    """
    historical_item = getattr(item_part, "historical_item", None)
    shelfmark = get_attr(item_part, "current_item__shelfmark")
    return {
        "repository_name": get_attr(item_part, "current_item__repository__name"),
        "repository_city": get_attr(item_part, "current_item__repository__place"),
        "shelfmark": shelfmark,
        "shelfmark_sort": natural_sort_key(shelfmark),
        "type": get_attr(historical_item, "type"),
        **date_fields(getattr(historical_item, "date", None)),
    }


def catalogue_numbers(historical_item) -> list[str]:
    """The manuscript's catalogue numbers as a list (`["Ker 236", "Lawrie 12"]`): one value per facet entry.

    Each number keeps its source, as `str(CatalogueNumber)` renders it: a bare
    `236` is meaningless on its own. Reads the registry's prefetch, never a query.
    """
    if historical_item is None:
        return []
    return [str(number) for number in historical_item.catalogue_numbers.all()]


def text_context(image_text) -> dict:
    """The fields shared by every document derived from an `ImageText` row.

    The texts index emits one document per row; clauses, people and places fan
    a row out into several. All four copy the same manuscript context, and the
    sync deletes the fan-out documents by `image_text`, so that key is here too.
    """
    item_image = image_text.item_image
    item_part = getattr(item_image, "item_part", None)
    historical_item = getattr(item_part, "historical_item", None)
    return {
        "image_text": image_text.id,
        "item_image": item_image.id if item_image else None,
        "item_part": item_part.id if item_part else None,
        "text_type": image_text.type,
        **manuscript_context(item_part),
        "catalogue_numbers": catalogue_numbers(historical_item),
        "locus": item_image.locus if item_image else "",
        "status": image_text.status,
        "thumbnail_iiif": item_image.image.iiif.info if item_image else None,
    }


def drop_none(d: dict, *, keep: set[str] | None = None) -> dict:
    """Return a copy with None values removed (Meilisearch-friendly).

    Keys listed in *keep* are preserved even when their value is None.
    """
    return {k: v for k, v in d.items() if v is not None or k in (keep or ())}


def unique_preserve_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def annotation_json(annotation) -> str:
    """A graph's region as the JSON string the indexes store."""
    return json.dumps(annotation) if isinstance(annotation, dict) else str(annotation)


def graph_taxonomy(graphs) -> dict[str, list[str]]:
    """The deduplicated component, feature, component-feature and position names of *graphs*,
    read from the prefetches the registry declares."""
    components: list[str] = []
    features: list[str] = []
    component_features: list[str] = []
    positions: list[str] = []
    for graph in graphs:
        components.extend(component.name for component in graph.components.all())
        for gc in graph.graphcomponent_set.all():
            for feature in gc.features.all():
                features.append(feature.name)
                component_features.append(f"{gc.component.name} - {feature.name}")
        positions.extend(position.name for position in graph.positions.all())
    return {
        "components": unique_preserve_order(components),
        "features": unique_preserve_order(features),
        "component_features": unique_preserve_order(component_features),
        "positions": unique_preserve_order(positions),
    }


def region_coordinates(image_text) -> dict[int, str]:
    """``{graph id: coordinates JSON}`` for the regions a text can link to: the live, non-editorial
    graphs of its own image.

    Read from the image's `graphs` prefetch (the registry declares it), so a reindex
    costs no query per document. A link to a graph on another image is a data error
    (`check_text_links` reports it) and resolves to no coordinates. Editorial graphs are
    left out: these indexes are public, and editorial annotations are for signed-in
    users only.
    """
    graphs = getattr(getattr(image_text, "item_image", None), "graphs", None)
    if graphs is None:
        return {}
    out: dict[int, str] = {}
    for graph in graphs.all():
        if graph.annotation is None or graph.annotation_type == Graph.AnnotationType.EDITORIAL:
            continue
        out[graph.id] = annotation_json(graph.annotation)
    return out
