"""The tutor's tools: what it may look at, and how it hands its lesson back.

Each tool is a strict schema, so the model's arguments always match it, and a
function the loop runs. What the tools return comes from the platform's public
record and nothing else. Anyone with a lesson's link may read it, so nothing a
signed-out reader cannot see goes into one: no editorial annotations and no
draft transcriptions.

Two tools hand something to the student rather than gather for the tutor:
`present_walkthrough` ends the lesson's first turn, and `reply` answers a
question. They are handled by the loop, not here.

Every box is in the pixels of the session's picture, origin at the top left.
The platform stores annotation rings Y-up in the pixels of the full-size page,
so a ring is flipped with the page's full height and scaled to the picture.
"""

from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import logging
from typing import Any
import urllib.request

from django.db.models import Count, QuerySet

from apps.annotations.models import Graph, GraphComponent
from apps.manuscripts.models import ItemImage
from apps.scribes.models import Hand
from apps.symbols_structure.models import Allograph, AllographComponent
from apps.vision import images

from . import pictures

logger = logging.getLogger(__name__)

LOOK_CLOSER = "look_closer"
DESCRIBE_ALLOGRAPH = "describe_allograph"
CORPUS_EXAMPLES = "corpus_examples"
EXPERT_ANNOTATIONS = "expert_annotations"
PRESENT_WALKTHROUGH = "present_walkthrough"
REPLY = "reply"

# Placeholders in the taxonomy rather than letter-forms: the importer's bucket
# for unmapped allographs, and the form recorded when none was chosen.
NOT_FORMS = {"unmapped_allographs", "_unspecified"}
MAX_EXAMPLES = 8
# Candidates taken for each example asked for: a glyph whose page the image
# server cannot give is passed over for the next, rather than left a gap.
SPARE_EXAMPLES = 3
# Room around a glyph in its crop, as a fraction of its size on each side, so
# the letter is seen with its neighbours' strokes, as a reader sees it.
CROP_MARGIN = 0.25
CROP_SIDE = 360
CROP_TIMEOUT = 20
MAX_CROP_BYTES = 2 * 1024 * 1024
FETCH_WORKERS = 8
# Quarter-centuries are as fine as the corpus's dating supports: most charters
# are dated to a reign or a span of years.
DATE_BUCKET = 25


class ToolError(Exception):
    """A call the tool cannot answer. The message goes back to the model."""


@dataclass
class Desk:
    """What the tools work from: the session's picture, and its corpus page if it has one."""

    picture: bytes
    width: int
    height: int
    page: ItemImage | None = None
    # The page's full size, once measured: annotation rings are in its pixels.
    page_size: tuple[int, int] | None = None
    # Glyph ids a tool has shown the tutor, which are the only ones a lesson may cite.
    seen: set[int] = field(default_factory=set)


@dataclass
class Result:
    """What a tool hands back: its answer, any pictures, and a line for the student's progress."""

    text: str
    images: list[tuple[str, bytes]] = field(default_factory=list)
    progress: str = ""
    error: bool = False


def _box_schema(description: str, *, labelled: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "x": {"type": "integer", "description": "Left edge, in pixels from the picture's left side."},
        "y": {"type": "integer", "description": "Top edge, in pixels from the picture's top."},
        "width": {"type": "integer", "description": "Width in pixels."},
        "height": {"type": "integer", "description": "Height in pixels."},
    }
    if labelled:
        properties["label"] = {"type": "string", "description": "A word or two naming what the box shows."}
    return {
        "type": "object",
        "description": description,
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_NULLABLE_ALLOGRAPH = {
    "anyOf": [{"type": "integer"}, {"type": "null"}],
    "description": "The allograph's id from the taxonomy, or null if the step is not about one letter-form.",
}

_LOOK_CLOSER = {
    "name": LOOK_CLOSER,
    "description": (
        "See part of the picture enlarged, up to four times, so that its longer side is about 1400 pixels. "
        "Look closer before you describe a letter's form or read a line: the whole picture is too small to "
        "be sure of a stroke. The answer gives the scale, and a point (px, py) in the enlargement is "
        "(box.x + px / scale, box.y + py / scale) in the picture."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Why, in a few words a student would follow, e.g. 'to read the first line'.",
            },
            "box": _box_schema("The region to enlarge, in the picture's pixels."),
        },
        "required": ["reason", "box"],
        "additionalProperties": False,
    },
}

_DESCRIBE_ALLOGRAPH = {
    "name": DESCRIBE_ALLOGRAPH,
    "description": (
        "How the platform describes one letter-form (allograph): its parts (components), the features "
        "experts record for each part, how often each feature is recorded on this corpus's examples, how "
        "many examples are annotated, which hands write most of them, and when the charters that have "
        "it were written."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"allograph_id": {"type": "integer", "description": "The allograph's id from the taxonomy."}},
        "required": ["allograph_id"],
        "additionalProperties": False,
    },
}

_CORPUS_EXAMPLES = {
    "name": CORPUS_EXAMPLES,
    "description": (
        "Pictures of one letter-form as experts annotated it in other charters of the corpus, from as many "
        "different hands as there are, each with its glyph id, charter, date, hand and recorded features. "
        "A lesson may show the student only examples this tool has returned, by their glyph ids."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why, in a few words a student would follow."},
            "allograph_id": {"type": "integer", "description": "The allograph's id from the taxonomy."},
            "count": {"type": "integer", "description": f"How many examples, from 1 to {MAX_EXAMPLES}."},
        },
        "required": ["reason", "allograph_id", "count"],
        "additionalProperties": False,
    },
}

_EXPERT_ANNOTATIONS = {
    "name": EXPERT_ANNOTATIONS,
    "description": (
        "The glyphs experts have annotated on this page, grouped by letter-form, each with its glyph id, "
        "its box in the picture's pixels and its hand. Use them to point at letters precisely and to check "
        "your own identifications."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "allograph_id": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "description": "Only this letter-form's glyphs, or null for all of them.",
            }
        },
        "required": ["allograph_id"],
        "additionalProperties": False,
    },
}

_STEP = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "A short heading, e.g. 'The long s'."},
        "explanation": {
            "type": "string",
            "description": "Two to five sentences: what to look at, how to recognise it, and why it matters.",
        },
        "boxes": {
            "type": "array",
            "description": "Where on the picture to look: one to six boxes around what the step is about.",
            "items": _box_schema("A place on the picture.", labelled=True),
        },
        "character": {"type": "string", "description": "The character the step is about, or '' if none."},
        "allograph_id": _NULLABLE_ALLOGRAPH,
        "look_for": {
            "type": "array",
            "description": "Two to four short cues for telling this form apart, e.g. 'descends below the line'.",
            "items": {"type": "string"},
        },
        "example_glyph_ids": {
            "type": "array",
            "description": "Up to six glyph ids from corpus_examples or expert_annotations to show beside the step.",
            "items": {"type": "integer"},
        },
    },
    "required": ["title", "explanation", "boxes", "character", "allograph_id", "look_for", "example_glyph_ids"],
    "additionalProperties": False,
}

_PRESENT_WALKTHROUGH = {
    "name": PRESENT_WALKTHROUGH,
    "description": (
        "Hand the student the finished lesson. Call it once, when you have looked closely enough to be sure "
        "of every box and every letter-form you name. The student sees nothing until you do."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A title for the lesson."},
            "overview": {
                "type": "string",
                "description": "What the picture is and what the student will learn from it, in a short paragraph.",
            },
            "script": {
                "type": "object",
                "description": "The script, as a palaeographer would name it, and the evidence for that.",
                "properties": {
                    "name": {"type": "string", "description": "e.g. 'Protogothic charter minuscule'."},
                    "date": {
                        "type": "string",
                        "description": "When the hand was likely written, as a range, e.g. 'c. 1170-1200'.",
                    },
                    "reasons": {
                        "type": "array",
                        "description": "Two to five observations on the picture that support the name and date.",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name", "date", "reasons"],
                "additionalProperties": False,
            },
            "steps": {
                "type": "array",
                "description": (
                    "Four to seven steps, in the order a student should take them; none if the picture "
                    "is not of handwriting, with the overview saying so."
                ),
                "items": _STEP,
            },
            "practice": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "instructions": {
                                "type": "string",
                                "description": "What to try, e.g. 'Read the second line, expanding the abbreviations'.",
                            },
                            "box": _box_schema("The line or passage to practise on."),
                            "reading": {
                                "type": "string",
                                "description": "Its reading, abbreviations expanded in round brackets.",
                            },
                            "note": {
                                "type": "string",
                                "description": (
                                    "What the reading rests on: the edition, or your own reading and how sure it is."
                                ),
                            },
                        },
                        "required": ["instructions", "box", "reading", "note"],
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ],
                "description": "A short passage for the student to read, or null if none is legible enough.",
            },
        },
        "required": ["title", "overview", "script", "steps", "practice"],
        "additionalProperties": False,
    },
}

_REPLY = {
    "name": REPLY,
    "description": "Answer the student's question. Call it once, as the last thing you do for that question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The answer, in plain prose."},
            "boxes": {
                "type": "array",
                "description": "Places on the picture the answer points at; empty if none.",
                "items": _box_schema("A place on the picture.", labelled=True),
            },
            "example_glyph_ids": {
                "type": "array",
                "description": "Up to six glyph ids from corpus_examples or expert_annotations to show; empty if none.",
                "items": {"type": "integer"},
            },
        },
        "required": ["text", "boxes", "example_glyph_ids"],
        "additionalProperties": False,
    },
}


def definitions(*, annotated: bool) -> list[dict[str, Any]]:
    """The tools offered to a session, `expert_annotations` only for a page experts annotated.

    One list for the whole session: a conversation's tools are part of what a
    replayed thinking block is checked against, so the same list is sent on
    every turn, the lesson's and every question's.
    """
    offered = [_LOOK_CLOSER, _DESCRIBE_ALLOGRAPH, _CORPUS_EXAMPLES]
    if annotated:
        offered.append(_EXPERT_ANNOTATIONS)
    offered += [_PRESENT_WALKTHROUGH, _REPLY]
    return [{**tool, "strict": True} for tool in offered]


def forms() -> list[Allograph]:
    """The taxonomy's letter-forms, placeholders left out."""
    return list(
        Allograph.objects.select_related("character").exclude(name__in=NOT_FORMS).order_by("character__name", "name")
    )


def taxonomy() -> str:
    """The taxonomy as the tutor reads it: one line per allograph, with its id."""
    lines = []
    for form in forms():
        label = form.character.name if form.name == form.character.name else f"{form.character.name}, {form.name}"
        lines.append(f"{form.pk}: {label} ({form.character.type or 'other'})")
    return "\n".join(lines)


def annotated(page: ItemImage | None) -> bool:
    return bool(page is not None and page_glyphs(page).exists())


def public_glyphs() -> QuerySet[Graph]:
    """Glyphs a lesson may show. Image glyphs only: editorial annotations are for signed-in readers."""
    return Graph.objects.filter(annotation_type=Graph.AnnotationType.IMAGE, allograph__isnull=False)


def page_glyphs(page: ItemImage) -> QuerySet[Graph]:
    return public_glyphs().filter(item_image=page)


def _form(allograph_id: Any) -> Allograph:
    try:
        form: Allograph = (
            Allograph.objects.select_related("character").exclude(name__in=NOT_FORMS).get(pk=int(allograph_id))
        )
    except (Allograph.DoesNotExist, TypeError, ValueError):  # fmt: skip
        raise ToolError(f"There is no allograph {allograph_id!r} in the taxonomy.") from None
    return form


def _label(form: Allograph) -> str:
    return form.character.name if form.name == form.character.name else f"{form.character.name} ({form.name})"


def run(name: str, arguments: dict[str, Any], desk: Desk) -> Result:
    """Run one gathering tool. A `ToolError` becomes an error the model can act on."""
    handlers = {
        LOOK_CLOSER: look_closer,
        DESCRIBE_ALLOGRAPH: describe_allograph,
        CORPUS_EXAMPLES: corpus_examples,
        EXPERT_ANNOTATIONS: expert_annotations,
    }
    handler = handlers.get(name)
    if handler is None:
        return Result(f"There is no tool called {name!r}.", error=True)
    try:
        return handler(arguments, desk)
    except ToolError as exc:
        return Result(str(exc), error=True)
    except images.ImageUnavailable as exc:
        logger.warning("Tutor tool %s could not reach an image: %s", name, exc)
        return Result(f"The image server could not provide that just now ({exc}).", error=True)


def look_closer(arguments: dict[str, Any], desk: Desk) -> Result:
    box = pictures.clamp(arguments.get("box") or {}, width=desk.width, height=desk.height)
    if box is None:
        raise ToolError(f"That box is not on the picture, which is {desk.width} by {desk.height} pixels.")
    jpeg, scale = pictures.closer_look(desk.picture, box)
    caption = f"The region x={box['x']}, y={box['y']}, width={box['width']}, height={box['height']}, enlarged {scale}×."
    reason = str(arguments.get("reason") or "").strip()
    return Result(
        caption, images=[(caption, jpeg)], progress=f"Looking closer: {reason}" if reason else "Looking closer"
    )


def _dated(graphs) -> dict[str, int]:
    """How many glyphs come from charters of each quarter-century, by the middle of each charter's date."""
    buckets: dict[int, int] = defaultdict(int)
    for low, high in graphs.values_list(
        "item_image__item_part__historical_item__date__min_weight",
        "item_image__item_part__historical_item__date__max_weight",
    ):
        if low is None or high is None:
            continue
        middle = (int(low) + int(high)) // 2
        buckets[middle - middle % DATE_BUCKET] += 1
    return {f"{start}-{start + DATE_BUCKET - 1}": count for start, count in sorted(buckets.items())}


def describe_allograph(arguments: dict[str, Any], desk: Desk) -> Result:
    form = _form(arguments.get("allograph_id"))
    glyphs = public_glyphs().filter(allograph=form)
    recorded: dict[str, dict[str, int]] = defaultdict(dict)
    rows = (
        GraphComponent.objects.filter(graph__in=glyphs, features__isnull=False)
        .values_list("component__name", "features__name")
        .annotate(n=Count("id"))
    )
    for component, feature, count in rows:
        recorded[component][feature] = count
    described = GraphComponent.objects.filter(graph__in=glyphs, features__isnull=False).values("graph").distinct()
    components = [
        {
            "component": part.component.name,
            "features_experts_record": _recordable(part),
            "recorded_on_examples": dict(sorted(recorded.get(part.component.name, {}).items(), key=lambda kv: -kv[1])),
        }
        for part in AllographComponent.objects.filter(allograph=form)
        .select_related("component")
        .prefetch_related("features", "component__features")
    ]
    hands = _top_hands(glyphs)
    answer = {
        "allograph_id": form.pk,
        "character": form.character.name,
        "form": form.name,
        "type": form.character.type or "",
        "annotated_examples": glyphs.count(),
        "examples_with_features_recorded": described.count(),
        "components": components,
        "hands_with_most_examples": hands,
        "examples_by_date_of_charter": _dated(glyphs),
    }
    return Result(json.dumps(answer, ensure_ascii=False), progress=f"Reading up on {_label(form)}")


def _recordable(part: AllographComponent) -> list[str]:
    """The features experts may record on a form's part.

    The taxonomy names them for the form where it narrows them, and for the
    part in general otherwise; a form that names none takes the part's.
    """
    features = part.features.all() or part.component.features.all()
    return sorted(feature.name for feature in features)


def _top_hands(glyphs) -> list[dict[str, Any]]:
    """The five hands with the most examples, with the charter each wrote."""
    counts = {row["hand_id"]: row["n"] for row in glyphs.values("hand_id").annotate(n=Count("id")).order_by("-n")[:5]}
    hands = [
        {
            "hand": str(hand),
            "charter": str(hand.item_part.historical_item),
            "date": str(hand.item_part.historical_item.date) if hand.item_part.historical_item.date_id else "",
            "examples": counts[hand.pk],
        }
        for hand in Hand.objects.filter(pk__in=counts).select_related("item_part__historical_item__date")
    ]
    return sorted(hands, key=lambda hand: (-hand["examples"], hand["hand"]))


def _features(graph: Graph) -> dict[str, list[str]]:
    recorded: dict[str, list[str]] = {}
    for part in graph.graphcomponent_set.all():
        names = sorted(feature.name for feature in part.features.all())
        if names:
            recorded[part.component.name] = names
    return recorded


def ring_box(annotation: Any) -> tuple[float, float, float, float] | None:
    """A stored ring's bounds in the full-size page: (left, lower, right, upper), Y-up."""
    try:
        data = json.loads(annotation) if isinstance(annotation, str) else annotation
        geometry = data.get("geometry", {}) if data.get("type") == "Feature" else data
        if geometry.get("type") != "Polygon":
            return None
        ring = geometry["coordinates"][0]
        xs = [float(point[0]) for point in ring]
        ys = [float(point[1]) for point in ring]
    except (AttributeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):  # fmt: skip
        return None
    if not xs or max(xs) <= min(xs) or max(ys) <= min(ys):
        return None
    return min(xs), min(ys), max(xs), max(ys)


def glyph_region(annotation: Any, *, page_height: int, margin: float = CROP_MARGIN) -> str | None:
    """The IIIF region of a glyph with room around it, Y-down, or None if its ring cannot be read."""
    bounds = ring_box(annotation)
    if bounds is None:
        return None
    left, lower, right, upper = bounds
    pad_x, pad_y = (right - left) * margin, (upper - lower) * margin
    x = max(0.0, left - pad_x)
    y = max(0.0, page_height - upper - pad_y)
    return f"{int(x)},{int(y)},{max(1, int(right - left + 2 * pad_x))},{max(1, int(upper - lower + 2 * pad_y))}"


def picture_box(annotation: Any, desk: Desk) -> dict[str, int] | None:
    """A stored ring as a box in the session's picture, or None if it falls outside it."""
    bounds = ring_box(annotation)
    if bounds is None or desk.page_size is None:
        return None
    full_width, full_height = desk.page_size
    left, lower, right, upper = bounds
    scale = desk.width / full_width if full_width else 0.0
    box = {
        "x": left * scale,
        "y": (full_height - upper) * scale,
        "width": (right - left) * scale,
        "height": (upper - lower) * scale,
    }
    return pictures.clamp(box, width=desk.width, height=desk.height)


def _crop(graph: Graph) -> bytes:
    _, height = images.dimensions(graph.item_image)
    region = glyph_region(graph.annotation, page_height=height)
    if region is None:
        raise images.ImageUnavailable(f"Glyph {graph.pk} has no outline to crop.")
    url = f"{images.internal_identifier(graph.item_image)}/{region}/%5E!{CROP_SIDE},{CROP_SIDE}/0/default.jpg"
    try:
        with urllib.request.urlopen(url, timeout=CROP_TIMEOUT) as response:
            data: bytes = response.read(MAX_CROP_BYTES + 1)
    except OSError as exc:
        raise images.ImageUnavailable(f"Could not fetch glyph {graph.pk}: {exc}") from exc
    if not data or len(data) > MAX_CROP_BYTES:
        raise images.ImageUnavailable(f"The crop of glyph {graph.pk} came back empty or too large.")
    return data


def _crop_or_none(graph: Graph) -> bytes | None:
    try:
        return _crop(graph)
    except images.ImageUnavailable as exc:
        logger.info("Tutor skipped an example: %s", exc)
        return None


def choose_examples(form: Allograph, count: int, *, exclude_page: int | None = None) -> list[Graph]:
    """Examples of a form from as many hands as possible, those with features recorded first.

    One per hand before a second from any: a student learns a letter-form from
    its range, and five examples by one scribe show only that scribe's habit.
    """
    candidates = (
        public_glyphs()
        .filter(allograph=form)
        .annotate(recorded=Count("graphcomponent__features"))
        .order_by("-recorded", "id")
        .values_list("pk", "hand_id", "item_image__item_part_id")
    )
    if exclude_page is not None:
        candidates = candidates.exclude(item_image_id=exclude_page)
    chosen: list[int] = []
    hands: set[int] = set()
    charters: set[int] = set()
    rest: list[tuple[int, int]] = []
    for pk, hand_id, part_id in candidates:
        if hand_id not in hands and part_id not in charters:
            chosen.append(pk)
            hands.add(hand_id)
            charters.add(part_id)
            if len(chosen) == count:
                break
        else:
            rest.append((pk, part_id))
    for pk, part_id in rest:
        if len(chosen) == count:
            break
        if part_id not in charters:
            chosen.append(pk)
            charters.add(part_id)
    for pk, _ in rest:
        if len(chosen) == count:
            break
        if pk not in chosen:
            chosen.append(pk)
    by_pk = {
        graph.pk: graph
        for graph in Graph.objects.filter(pk__in=chosen)
        .select_related("hand", "allograph__character", "item_image__item_part__historical_item__date")
        .prefetch_related("graphcomponent_set__component", "graphcomponent_set__features")
    }
    return [by_pk[pk] for pk in chosen if pk in by_pk]


def corpus_examples(arguments: dict[str, Any], desk: Desk) -> Result:
    form = _form(arguments.get("allograph_id"))
    try:
        count = max(1, min(int(arguments.get("count", 4)), MAX_EXAMPLES))
    except (TypeError, ValueError):  # fmt: skip
        count = 4
    chosen = choose_examples(form, count * SPARE_EXAMPLES, exclude_page=desk.page.pk if desk.page is not None else None)
    if not chosen:
        raise ToolError(f"No other charter in the corpus has an annotated example of {_label(form)}.")
    with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, len(chosen))) as pool:
        crops = list(pool.map(_crop_or_none, chosen))
    shown: list[tuple[str, bytes]] = []
    for graph, data in zip(chosen, crops, strict=True):
        if data is None:
            continue
        if len(shown) == count:
            break
        historical = graph.item_image.item_part.historical_item
        details = {
            "glyph_id": graph.pk,
            "charter": str(historical),
            "page": str(graph.item_image),
            "date": str(historical.date) if historical.date_id else "",
            "hand": str(graph.hand) if graph.hand_id else "",
            "features": _features(graph),
        }
        shown.append((json.dumps(details, ensure_ascii=False), data))
        desk.seen.add(graph.pk)
    if not shown:
        raise images.ImageUnavailable(f"none of the {len(chosen)} examples of {_label(form)} could be fetched")
    summary = (
        f"{len(shown)} examples of {_label(form)} (allograph {form.pk}) from other charters, each before its picture."
    )
    return Result(summary, images=shown, progress=f"Finding examples of {_label(form)} in other charters")


def expert_annotations(arguments: dict[str, Any], desk: Desk) -> Result:
    if desk.page is None:
        raise ToolError("This picture is not from the corpus, so no expert has annotated it.")
    if desk.page_size is None:
        desk.page_size = images.dimensions(desk.page)
    glyphs = page_glyphs(desk.page).select_related("allograph__character", "hand")
    wanted = arguments.get("allograph_id")
    if wanted is not None:
        glyphs = glyphs.filter(allograph=_form(wanted))
    groups: dict[int, dict[str, Any]] = {}
    for graph in glyphs.order_by("allograph_id", "id"):
        box = picture_box(graph.annotation, desk)
        if box is None:
            continue
        group = groups.setdefault(
            graph.allograph_id,
            {"allograph_id": graph.allograph_id, "letter_form": _label(graph.allograph), "glyphs": []},
        )
        group["glyphs"].append(
            {"glyph_id": graph.pk, "box": [box["x"], box["y"], box["width"], box["height"]], "hand": str(graph.hand)}
        )
        desk.seen.add(graph.pk)
    if not groups:
        raise ToolError("Experts have annotated no such glyph on this page.")
    total = sum(len(group["glyphs"]) for group in groups.values())
    answer = {
        "boxes_are": "[x, y, width, height] in the picture's pixels",
        "glyphs": total,
        "letter_forms": list(groups.values()),
    }
    return Result(json.dumps(answer, ensure_ascii=False), progress="Checking the experts' annotations of this page")


SHOWN_CROP_SIDE = 240


def shown(glyph_ids: Iterable[int]) -> dict[str, dict[str, Any]]:
    """What the student's page shows of each glyph a lesson cites: its crop and where it comes from.

    Resolved once, when the lesson is settled, so that reading a lesson asks
    the image server nothing. A glyph whose page cannot be measured is shown
    without its crop rather than with a mirrored one.
    """
    graphs = (
        public_glyphs()
        .filter(pk__in=set(glyph_ids))
        .select_related("allograph__character", "hand", "item_image__item_part__historical_item__date")
    )
    resolved: dict[str, dict[str, Any]] = {}
    for graph in graphs:
        page = graph.item_image
        historical = page.item_part.historical_item
        crop_url = None
        try:
            _, height = images.dimensions(page)
            region = glyph_region(graph.annotation, page_height=height)
            if region is not None:
                crop_url = f"{images.identifier(page)}/{region}/!{SHOWN_CROP_SIDE},{SHOWN_CROP_SIDE}/0/default.jpg"
        except images.ImageUnavailable as exc:
            logger.info("A lesson shows glyph %s without its crop: %s", graph.pk, exc)
        resolved[str(graph.pk)] = {
            "id": graph.pk,
            "allograph_id": graph.allograph_id,
            "letter_form": _label(graph.allograph),
            "hand": str(graph.hand) if graph.hand_id else "",
            "page": str(page),
            "item_image": page.pk,
            "charter": str(historical),
            "historical_item": historical.pk,
            "date": str(historical.date) if historical.date_id else "",
            "crop_url": crop_url,
        }
    return resolved
