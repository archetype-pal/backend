"""Reproduction rights — resolving them, and answering who may republish what.

The point of putting this in code rather than a spreadsheet is that
redistribution eligibility becomes *queryable* rather than remembered. A dataset
release asks `may_redistribute_crops(image)` and gets a defensible answer; a
funder asking "do you hold the rights?" gets `manage.py rights_report`.

Nothing here grants anything. Every field it reads starts at `unknown`, so the
honest default is refusal, and clearing an archive means recording that someone
actually asked and got an answer in writing.
"""

from dataclasses import dataclass
from typing import cast

from apps.manuscripts.models import ItemImage, Repository


@dataclass(frozen=True)
class ImageRights:
    """The reproduction terms that apply to one image."""

    repository: str
    rights_statement: str
    attribution: str
    derivative_release: str

    @property
    def crops_redistributable(self) -> bool:
        return self.derivative_release == cast(str, Repository.DerivativeRelease.PERMITTED)


def repository_for(image: ItemImage) -> Repository | None:
    """The holding repository, via the catalogue chain, or None if unrecorded."""
    item_part = getattr(image, "item_part", None)
    current_item = getattr(item_part, "current_item", None)
    return getattr(current_item, "repository", None)


def resolve(image: ItemImage) -> ImageRights:
    """Terms for *image*: its own override where set, else its repository's."""
    repository = repository_for(image)
    return ImageRights(
        repository=repository.label if repository else "",
        # The per-image override exists for the exception case — an item
        # licensed differently from the archive that holds it.
        rights_statement=image.rights_statement or (repository.rights_statement if repository else ""),
        attribution=repository.attribution if repository else "",
        derivative_release=(
            repository.derivative_release if repository else cast(str, Repository.DerivativeRelease.UNKNOWN)
        ),
    )


def may_redistribute_crops(image: ItemImage) -> bool:
    """Whether cropped pixels from *image* may be published.

    Deliberately the strict reading: anything not cleared in writing is refused.
    """
    return resolve(image).crops_redistributable


@dataclass(frozen=True)
class RepositoryClearance:
    """One repository's clearance state, and how much of the corpus it gates."""

    repository: str
    name: str
    derivative_release: str
    has_rights_statement: bool
    has_attribution: bool
    images: int
    annotated_images: int
    notes: str

    @property
    def cleared(self) -> bool:
        return self.derivative_release == cast(str, Repository.DerivativeRelease.PERMITTED)


def clearance_summary() -> list[RepositoryClearance]:
    """Per-repository clearance, for the report command and for W0.2's gate."""
    rows = []
    for repository in Repository.objects.all():
        images = ItemImage.objects.filter(item_part__current_item__repository=repository)
        rows.append(
            RepositoryClearance(
                repository=repository.label,
                name=repository.name,
                derivative_release=repository.derivative_release,
                has_rights_statement=bool(repository.rights_statement),
                has_attribution=bool(repository.attribution),
                images=images.count(),
                annotated_images=images.filter(graphs__annotation_type="image").distinct().count(),
                notes=repository.rights_notes,
            )
        )
    return rows
