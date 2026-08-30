"""Reproduction rights — AI programme W0.4.

The gate on every published deliverable, so the tests pin the direction it
fails in: nothing is redistributable until someone records that an archive said
yes, and a manifest never asserts terms it does not hold.
"""

import pytest

from apps.iiif_presentation.manifest import build_manifest
from apps.manuscripts.models import Repository
from apps.manuscripts.services import rights

from .factories import ItemImageFactory, ItemPartFactory, RepositoryFactory


@pytest.mark.django_db
class TestResolution:
    def test_unrecorded_rights_default_to_refusal(self):
        image = ItemImageFactory()

        terms = rights.resolve(image)

        assert terms.derivative_release == Repository.DerivativeRelease.UNKNOWN
        assert terms.crops_redistributable is False
        assert rights.may_redistribute_crops(image) is False

    def test_terms_come_from_the_holding_repository(self):
        repository = RepositoryFactory(
            rights_statement="https://rightsstatements.org/vocab/InC-EDU/1.0/",
            attribution="Reproduced by permission of the Example Archive.",
            derivative_release=Repository.DerivativeRelease.PERMITTED,
        )
        image = ItemImageFactory(item_part=ItemPartFactory(current_item__repository=repository))

        terms = rights.resolve(image)

        assert terms.rights_statement == "https://rightsstatements.org/vocab/InC-EDU/1.0/"
        assert terms.attribution == "Reproduced by permission of the Example Archive."
        assert rights.may_redistribute_crops(image) is True

    def test_a_per_image_override_wins(self):
        repository = RepositoryFactory(rights_statement="https://example.org/repo-terms")
        image = ItemImageFactory(
            item_part=ItemPartFactory(current_item__repository=repository),
            rights_statement="https://creativecommons.org/publicdomain/mark/1.0/",
        )

        assert rights.resolve(image).rights_statement == "https://creativecommons.org/publicdomain/mark/1.0/"

    @pytest.mark.parametrize(
        "release",
        [
            Repository.DerivativeRelease.UNKNOWN,
            Repository.DerivativeRelease.PENDING,
            Repository.DerivativeRelease.PROHIBITED,
        ],
    )
    def test_only_written_permission_clears_crops(self, release):
        repository = RepositoryFactory(derivative_release=release)
        image = ItemImageFactory(item_part=ItemPartFactory(current_item__repository=repository))

        assert rights.may_redistribute_crops(image) is False


@pytest.mark.django_db
class TestClearanceSummary:
    def test_counts_images_per_repository(self):
        repository = RepositoryFactory(derivative_release=Repository.DerivativeRelease.PERMITTED)
        part = ItemPartFactory(current_item__repository=repository)
        ItemImageFactory(item_part=part)
        ItemImageFactory(item_part=part)

        row = next(r for r in rights.clearance_summary() if r.repository == repository.label)

        assert row.images == 2
        assert row.cleared is True


@pytest.mark.django_db
class TestManifestAssertions:
    def _manifest(self, image):
        return build_manifest(
            image.item_part,
            images=[image],
            texts_by_image={},
            graph_lookup={},
            base_url="http://testserver",
            dims=lambda identifier: (100, 100),
        )

    def test_a_manifest_asserts_recorded_terms(self):
        repository = RepositoryFactory(
            rights_statement="https://rightsstatements.org/vocab/InC/1.0/",
            attribution="Example Archive",
        )
        image = ItemImageFactory(item_part=ItemPartFactory(current_item__repository=repository))

        manifest = self._manifest(image)

        assert manifest["rights"] == "https://rightsstatements.org/vocab/InC/1.0/"
        assert manifest["requiredStatement"]["value"]["en"] == ["Example Archive"]

    def test_a_manifest_asserts_nothing_when_terms_are_unrecorded(self):
        """An empty `rights` reads as "no rights reserved"; omission is honest."""
        image = ItemImageFactory()

        manifest = self._manifest(image)

        assert "rights" not in manifest
        assert "requiredStatement" not in manifest
