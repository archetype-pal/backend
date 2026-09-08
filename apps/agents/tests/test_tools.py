"""The tool surface: what it returns, and what it refuses.

The refusals matter more than the returns. §8.5's rule is that least privilege
is enforced by the credential rather than the prompt, and the only way to know
that holds is to call a tool the identity was never granted and watch it fail.
"""

from unittest import mock

import pytest

from apps.agents import tools
from apps.agents.models import ServiceIdentity
from apps.annotations.models import Graph
from apps.diplomatic.models import CharterEntity, Relation
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory

ALL_TOOLS = [
    "search_charters",
    "get_charter",
    "get_image_regions",
    "cite_record",
    "fetch_witnesses",
    "fetch_relations",
    "compare_hands",
]


@pytest.fixture
def identity(db):
    return ServiceIdentity.objects.create(slug="test-agent", allowed_tools=ALL_TOOLS, enabled=True)


@pytest.fixture
def published(db):
    return ImageTextFactory(
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        content="<p>Sciant presentes et futuri quod ego David rex Scottorum</p>",
    )


@pytest.mark.django_db
class TestAllowList:
    def test_a_tool_not_granted_is_refused_even_when_it_exists(self, published):
        narrow = ServiceIdentity.objects.create(slug="narrow", allowed_tools=["search_charters"], enabled=True)

        with pytest.raises(tools.ToolError, match="not permitted"):
            tools.invoke(narrow, "get_charter", {"image_text_id": published.pk})

    def test_an_invented_tool_name_is_refused(self, identity):
        with pytest.raises(tools.ToolError, match="No such tool"):
            tools.invoke(identity, "delete_everything", {})

    def test_an_unexpected_argument_is_refused(self, identity, published):
        with pytest.raises(tools.ToolError, match="Unexpected arguments"):
            tools.invoke(identity, "get_charter", {"image_text_id": published.pk, "as_user": "admin"})

    def test_only_granted_and_answerable_tools_are_offered(self, identity, published):
        offered = {tool.name for tool in tools.available_for(identity)}

        # Granted but unanswerable: no encoder, and nothing approved yet.
        assert "compare_hands" not in offered
        assert "fetch_witnesses" not in offered
        assert {"search_charters", "get_charter", "cite_record"} <= offered

    def test_a_tool_becomes_available_when_the_data_does(self, identity, published):
        CharterEntity.objects.create(image_text=published, role=CharterEntity.Role.WITNESS, name="Walterus")

        assert "fetch_witnesses" in {tool.name for tool in tools.available_for(identity)}

    def test_hand_comparison_says_why_it_cannot_run(self, identity, published):
        with pytest.raises(tools.ToolError, match="W1.2/W1.3"):
            tools.invoke(identity, "compare_hands", {"left_image_text_id": 1, "right_image_text_id": 2})


@pytest.mark.django_db
class TestSearch:
    def test_a_phrase_finds_its_charter_with_a_snippet(self, identity, published):
        result = tools.invoke(identity, "search_charters", {"query": "David rex"})

        assert result["count"] == 1
        assert "David rex" in result["results"][0]["snippet"]
        assert result["results"][0]["image_text_id"] == published.pk

    def test_markup_is_not_returned_to_the_model(self, identity, published):
        result = tools.invoke(identity, "search_charters", {"query": "Sciant"})

        assert "<p>" not in result["results"][0]["snippet"]

    def test_an_unpublished_draft_is_invisible(self, identity):
        ImageTextFactory(status=ImageText.Status.DRAFT, content="Sciant presentes")

        assert tools.invoke(identity, "search_charters", {"query": "Sciant"})["count"] == 0

    def test_a_two_character_query_is_refused(self, identity):
        with pytest.raises(tools.ToolError, match="three characters"):
            tools.invoke(identity, "search_charters", {"query": "ex"})

    def test_the_result_count_is_capped_however_large_the_limit(self, identity):
        for _ in range(30):
            ImageTextFactory(status=ImageText.Status.LIVE, content="Sciant presentes")

        result = tools.invoke(identity, "search_charters", {"query": "Sciant", "limit": 500})

        assert result["count"] == tools.MAX_RESULTS


@pytest.mark.django_db
class TestGetCharter:
    def test_a_charter_comes_back_with_its_shelfmark_and_folio(self, identity, published):
        result = tools.invoke(identity, "get_charter", {"image_text_id": published.pk})

        assert result["shelfmark"] == published.item_image.item_part.current_item.shelfmark
        assert result["locus"] == published.item_image.locus
        assert result["text"].startswith("Sciant")

    def test_a_missing_charter_is_an_error_the_model_can_read(self, identity):
        with pytest.raises(tools.ToolError, match="No published charter text"):
            tools.invoke(identity, "get_charter", {"image_text_id": 999999})


@pytest.mark.django_db
class TestCiteRecord:
    def test_a_resolvable_anchor_is_returned_as_a_citation(self, identity, published):
        result = tools.invoke(
            identity, "cite_record", {"claim": "David I granted this.", "image_text_id": published.pk}
        )

        assert result["cited"]["claim"] == "David I granted this."
        assert result["cited"]["image_text_id"] == published.pk

    def test_an_invented_charter_id_is_refused(self, identity):
        with pytest.raises(tools.ToolError, match="no such published charter"):
            tools.invoke(identity, "cite_record", {"claim": "x", "image_text_id": 999999})

    def test_a_citation_pointing_at_the_wrong_folio_is_refused(self, identity, published):
        other = ItemImageFactory()

        with pytest.raises(tools.ToolError, match="wrong folio"):
            tools.invoke(
                identity,
                "cite_record",
                {"claim": "x", "image_text_id": published.pk, "item_image_id": other.pk},
            )

    def test_a_malformed_region_is_refused(self, identity, published):
        with pytest.raises(tools.ToolError, match="four integers"):
            tools.invoke(identity, "cite_record", {"claim": "x", "image_text_id": published.pk, "region": "top left"})

    def test_a_region_the_platform_did_not_compute_is_not_certified(self, identity, published):
        result = tools.invoke(
            identity,
            "cite_record",
            {"claim": "x", "image_text_id": published.pk, "region": "10,10,50,50"},
        )

        # Accepted as an anchor, but never marked verified: only a region derived
        # from a stored annotation is known to be right.
        assert result["cited"]["region"] == "10,10,50,50"
        assert result["cited"]["verified_region"] is False

    def test_a_citation_without_a_claim_is_refused(self, identity, published):
        with pytest.raises(tools.ToolError, match="needs the claim"):
            tools.invoke(identity, "cite_record", {"claim": "  ", "image_text_id": published.pk})


@pytest.mark.django_db
class TestImageRegions:
    """The Y-flip, at the surface a citation is built from.

    Stored rings are Y-up and IIIF is Y-down, so a region computed without the
    page height is mirrored — plausible, clickable and wrong. Both branches are
    pinned here because the failure is invisible in the output.
    """

    def _annotate(self, image):
        return Graph.objects.create(
            item_image=image,
            annotation={
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[10, 10], [60, 10], [60, 60], [10, 60]]]},
            },
        )

    def test_a_known_page_height_flips_the_ring_into_a_iiif_region(self, identity, published):
        self._annotate(published.item_image)

        with mock.patch("apps.manuscripts.services.regions._safe_dimensions", return_value=(800, 1000)):
            result = tools.invoke(identity, "get_image_regions", {"item_image_id": published.item_image_id})

        # y = 1000 - 10 - 50 = 940, not the stored 10.
        assert result["regions"][0]["region"] == "10,940,50,50"

    def test_a_region_is_dropped_when_the_page_height_is_unknown(self, identity, published):
        self._annotate(published.item_image)

        with mock.patch("apps.manuscripts.services.regions._safe_dimensions", return_value=None):
            result = tools.invoke(identity, "get_image_regions", {"item_image_id": published.item_image_id})

        assert result["count"] == 0
        assert "could not be resolved" in result["note"]

    def test_a_missing_image_is_an_error(self, identity):
        with pytest.raises(tools.ToolError, match="No image with id"):
            tools.invoke(identity, "get_image_regions", {"item_image_id": 999999})


@pytest.mark.django_db
class TestApprovedData:
    def test_witnesses_are_read_from_approved_entities_only(self, identity, published):
        CharterEntity.objects.create(image_text=published, role=CharterEntity.Role.WITNESS, name="Walterus")
        CharterEntity.objects.create(image_text=published, role=CharterEntity.Role.PLACE, name="Perth")

        result = tools.invoke(identity, "fetch_witnesses", {})

        assert [row["name"] for row in result["witnesses"]] == ["Walterus"]

    def test_relations_filter_by_predicate(self, identity, published):
        Relation.objects.create(
            image_text=published, subject="a", predicate=Relation.Predicate.WITNESSED_BY, object="b"
        )
        Relation.objects.create(image_text=published, subject="a", predicate=Relation.Predicate.GRANTED_BY, object="c")

        result = tools.invoke(identity, "fetch_relations", {"predicate": "granted_by"})

        assert result["count"] == 1
