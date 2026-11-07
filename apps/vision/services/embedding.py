"""Glyph vectors from a self-hosted encoder (AI programme W1.2).

Every glyph annotation can be turned into a vector by an encoder that runs on
our own server. Glyphs that look alike get vectors that lie close together,
which is what visual search (W1.2) and hand similarity (W1.3) are built on.

Two rules hold here:

- **Only a self-hosted encoder.** A crop is a piece of a photograph whose rights
  are not cleared (W0.4), so it may go to a model on our own server and nowhere
  else. A hosted provider is refused before a crop is fetched.
- **Every call goes through the ledger.** Each batch is one `MLJob`, whose params
  list the glyphs it embedded, and each stored vector points back at its job.

A crop is the glyph's bounding box, fetched from the image server at no more
than 224 pixels a side; each encoder fits and normalises it its own way.
"""

import base64
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import islice
import logging
from typing import Any
import urllib.request

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet, prefetch_related_objects

from apps.annotations.models import Graph
from apps.manuscripts.services.iiif import get_iiif_region_from_geojson
from apps.ml.models import MLJob
from apps.ml.providers import resolve_provider
from apps.ml.services import InferenceService

from .. import images
from ..models import GlyphEmbedding
from .glyph_search import ENCODERS as SEARCH_ENCODERS, search_vectors_changed

logger = logging.getLogger(__name__)

TASK = "W1.2"
DEFAULT_ENCODER = "trocr"
# Every encoder rescales a crop to its own size (384 for `trocr`, 32 or 48 for
# the shape descriptors), and all of them were measured on crops of this size.
# Asking the image server for it (`^` lets it scale a small glyph up) keeps
# each crop a few kilobytes.
CROP_SIZE = 224
MAX_CROP_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT = 20
# Crops are fetched in parallel; the image server is the bottleneck, not us.
FETCH_WORKERS = 8


class EncoderNotAllowed(ValueError):
    """The encoder is hosted, and a crop must not leave our infrastructure."""


@dataclass
class Tally:
    """What a pass did, glyph by glyph."""

    embedded: int = 0
    unavailable: int = 0
    failed: int = 0
    refused: str = ""
    jobs: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "embedded": self.embedded,
            "unavailable": self.unavailable,
            "failed": self.failed,
            "jobs": len(self.jobs),
        }


def glyphs_to_embed(encoder: str = DEFAULT_ENCODER, *, force: bool = False) -> QuerySet[Graph]:
    """Every glyph annotation, less those this encoder has a current vector for.

    A glyph redrawn since it was embedded, or whose page has been given
    another image, is embedded again: its vector was made from a crop it no
    longer has. Glyphs only: a text-region annotation outlines a line or a
    word, not a letter. Trashed annotations are already hidden by the manager.
    """
    queryset = Graph.objects.filter(annotation_type=Graph.AnnotationType.IMAGE).select_related("item_image")
    if not force:
        has_vector = GlyphEmbedding.objects.filter(graph=OuterRef("pk"), encoder=encoder)
        queryset = queryset.filter(~Exists(has_vector) | Q(pk__in=stale_glyphs(encoder)))
    return queryset.order_by("pk")


def stale_glyphs(encoder: str) -> list[int]:
    """The glyphs whose vector from `encoder` was made from a crop they no longer have."""
    rows = GlyphEmbedding.objects.filter(encoder=encoder).values_list(
        "graph_id", "crop_digest", "graph__item_image__image", "graph__annotation"
    )
    return [
        graph_id
        for graph_id, digest, image_path, outline in rows.iterator(chunk_size=2000)
        if digest != GlyphEmbedding.crop_digest_of(image_path, outline)
    ]


def crop(graph: Graph) -> str:
    """The glyph as a base64 PNG, at most `CROP_SIZE` a side.

    Raises `images.ImageUnavailable` when the page cannot be measured or
    fetched: a region located without the page height would be mirrored.
    """
    image = graph.item_image
    _, height = images.dimensions(image)
    region = get_iiif_region_from_geojson(graph.annotation, image_height=height)
    # Geometry it cannot read comes back as "full", the whole page: right for a
    # viewer, wrong for a glyph's vector.
    if region in ("", "full"):
        raise images.ImageUnavailable(f"Graph {graph.pk} has no region to crop.")
    url = f"{images.internal_identifier(image)}/{region}/%5E!{CROP_SIZE},{CROP_SIZE}/0/default.png"
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as response:
            data = response.read(MAX_CROP_BYTES + 1)
    except OSError as exc:
        raise images.ImageUnavailable(f"Could not fetch the crop of graph {graph.pk}: {exc}") from exc
    if not data or len(data) > MAX_CROP_BYTES:
        raise images.ImageUnavailable(f"The crop of graph {graph.pk} came back empty or too large.")
    return base64.b64encode(data).decode("ascii")


class _Cropper:
    """Crops for one pass, remembering the pages the image server cannot serve.

    A failed page lookup is not cached by `images.dimensions`, so without this
    every glyph on a missing page would ask the image server again, with its
    retries, and a corpus with a quarter of its pages missing would spend most
    of a pass on them.
    """

    def __init__(self) -> None:
        self.missing_pages: set[int] = set()

    def __call__(self, graph: Graph) -> str | None:
        if graph.item_image_id in self.missing_pages:
            return None
        try:
            images.dimensions(graph.item_image)
        except images.ImageUnavailable as exc:
            if graph.item_image_id not in self.missing_pages:
                self.missing_pages.add(graph.item_image_id)
                logger.info("Skipping image %s's glyphs: %s", graph.item_image_id, exc)
            return None
        try:
            return crop(graph)
        except images.ImageUnavailable as exc:
            logger.info("%s", exc)
            return None


def _batches(graphs: Iterable[Graph], size: int) -> Iterator[list[Graph]]:
    iterator = iter(graphs)
    while batch := list(islice(iterator, size)):
        yield batch


def embed_glyphs(
    graphs: Iterable[Graph],
    *,
    encoder: str = DEFAULT_ENCODER,
    batch_size: int = 32,
    actor: Any | None = None,
    on_batch: Callable[[Tally], None] | None = None,
) -> Tally:
    """Embed `graphs` with `encoder`, a batch per ledger row, and store the vectors.

    Stops at the first refusal: a refusal means inference is off or a cap is
    reached, and every later batch would be refused too. A failed batch is
    counted and skipped; the next may succeed.
    """
    if resolve_provider(encoder).hosted:
        raise EncoderNotAllowed(f"'{encoder}' is a hosted provider; glyph crops go only to a self-hosted encoder.")
    service = InferenceService()
    tally = Tally()
    cropper = _Cropper()

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        for batch in _batches(graphs, batch_size):
            # Load the pages here: the crop threads must not touch the database.
            prefetch_related_objects(batch, "item_image")
            crops = list(pool.map(cropper, batch))
            ready = [(graph, image) for graph, image in zip(batch, crops, strict=True) if image is not None]
            tally.unavailable += len(batch) - len(ready)
            if ready:
                job = _embed_batch(service, ready, encoder=encoder, actor=actor, tally=tally)
                if job.status == MLJob.Status.REFUSED:
                    tally.refused = job.error
                    break
            if on_batch:
                on_batch(tally)
    return tally


def _embed_batch(
    service: InferenceService, ready: list[tuple[Graph, str]], *, encoder: str, actor: Any | None, tally: Tally
) -> MLJob:
    inputs = {"images": [image for _, image in ready]}
    params = {"graph_ids": [graph.pk for graph, _ in ready]}
    job = service.submit(task=TASK, provider=encoder, inputs=inputs, params=params, actor=actor, dispatch=False)
    if job.status == MLJob.Status.REFUSED:
        return job
    job = service.run(job.pk, inputs=inputs, params=params)
    tally.jobs.append(job.pk)
    if job.status != MLJob.Status.SUCCEEDED:
        tally.failed += len(ready)
        return job

    output = getattr(job, "_output", {})
    dimensions = int(output["dimensions"])
    rows = [
        GlyphEmbedding(
            graph=graph,
            encoder=encoder,
            model_name=job.model_name,
            model_version=job.model_version,
            dimensions=dimensions,
            vector=GlyphEmbedding.pack(vector),
            # Of the graph as it was cropped: one redrawn meanwhile is stale at once.
            crop_digest=GlyphEmbedding.crop_digest_for(graph),
            ml_job=job,
        )
        for (graph, _), vector in zip(ready, output["vectors"], strict=True)
    ]
    with transaction.atomic():
        # Replace, not add: re-embedding with new weights must not leave the
        # old vector beside the new one.
        GlyphEmbedding.objects.filter(encoder=encoder, graph__in=[graph for graph, _ in ready]).delete()
        GlyphEmbedding.objects.bulk_create(rows)
    if encoder in SEARCH_ENCODERS:
        # `bulk_create` sends no signal, and the search index keeps a copy of each glyph's vector.
        search_vectors_changed.send(sender=GlyphEmbedding, graph_ids=[graph.pk for graph, _ in ready])
    tally.embedded += len(rows)
    return job
