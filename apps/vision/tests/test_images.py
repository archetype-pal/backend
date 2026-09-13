"""Geometry, and the fetch that feeds it.

The Y-flip has the whole file's attention. It has already shipped wrong once in
this codebase, and it fails silently: a mirrored box on a page of text is a
perfectly plausible box, in the wrong place, that nobody notices until a
palaeographer opens it.
"""

from unittest import mock

import pytest

from apps.manuscripts.iiif import get_iiif_region_from_geojson
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.vision import images


class TestRingFromBox:
    def test_a_top_left_box_becomes_a_top_of_page_ring(self):
        ring = images.ring_from_box({"x": 0.1, "y": 0.0, "w": 0.1, "h": 0.1}, width=1000, height=2000)

        ys = [point[1] for point in ring["geometry"]["coordinates"][0]]
        # Y-up storage: a box at the top of the page has *high* y values.
        assert max(ys) == 2000
        assert min(ys) == 1800

    def test_a_round_trip_through_the_iiif_converter_returns_the_original_box(self):
        """The property that matters: what goes in comes back out.

        A box a model reported at 20% down the page must render at 20% down the
        page. This composes the writer with the reader the viewer actually uses,
        so a sign error in either is caught rather than cancelling out only in
        code that never runs together.
        """
        ring = images.ring_from_box({"x": 0.2, "y": 0.2, "w": 0.1, "h": 0.05}, width=1000, height=2000)

        region = get_iiif_region_from_geojson(ring, image_height=2000)

        assert region == "200,400,100,100"

    def test_the_flip_is_not_symmetric_about_the_midline(self):
        """Guards the failure this exists to prevent.

        A box in the top quarter and its mirror in the bottom quarter must not
        produce the same ring — which is exactly what omitting the height does.
        """
        top = images.ring_from_box({"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}, width=1000, height=2000)
        bottom = images.ring_from_box({"x": 0.1, "y": 0.8, "w": 0.1, "h": 0.1}, width=1000, height=2000)

        assert top["geometry"]["coordinates"] != bottom["geometry"]["coordinates"]


class TestPlausible:
    @pytest.mark.parametrize(
        "box",
        [
            {"x": 0.1, "y": 0.1, "w": 0.02, "h": 0.03},
            {"x": 0.0, "y": 0.0, "w": 0.01, "h": 0.01},
        ],
    )
    def test_a_letter_sized_box_passes(self, box):
        assert images.plausible(box)

    @pytest.mark.parametrize(
        ("box", "why"),
        [
            ({"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}, "a quarter of the page is a text block, not a letter"),
            ({"x": 0.1, "y": 0.1, "w": 0.0, "h": 0.1}, "zero width is arithmetic that went wrong"),
            ({"x": -0.1, "y": 0.1, "w": 0.05, "h": 0.05}, "off the left edge"),
            ({"x": 0.98, "y": 0.1, "w": 0.05, "h": 0.05}, "runs off the right edge"),
            ({"x": 0.1, "y": 0.1, "w": 0.05}, "missing a dimension"),
            ({"x": "left", "y": 0.1, "w": 0.05, "h": 0.05}, "not a number"),
        ],
    )
    def test_an_implausible_box_is_rejected(self, box, why):
        assert not images.plausible(box), why


@pytest.mark.django_db
class TestFetching:
    def test_a_page_becomes_an_inline_data_url(self):
        image = ItemImageFactory()
        response = mock.MagicMock()
        response.read.return_value = b"\xff\xd8\xff-jpeg-bytes"
        response.__enter__.return_value = response

        with mock.patch("apps.vision.images.urllib.request.urlopen", return_value=response):
            url = images.data_url(image)

        assert url.startswith("data:image/jpeg;base64,")

    def test_an_oversized_page_is_refused_rather_than_sent(self):
        image = ItemImageFactory()
        response = mock.MagicMock()
        response.read.return_value = b"x" * (images.MAX_BYTES + 1)
        response.__enter__.return_value = response

        with mock.patch("apps.vision.images.urllib.request.urlopen", return_value=response):
            with pytest.raises(images.ImageUnavailable, match="larger than"):
                images.data_url(image)

    def test_an_unreachable_image_server_is_an_error_not_an_empty_answer(self):
        image = ItemImageFactory()

        with mock.patch("apps.vision.images.urllib.request.urlopen", side_effect=OSError("refused")):
            with pytest.raises(images.ImageUnavailable, match="Could not fetch"):
                images.data_url(image)

    def test_unresolvable_dimensions_raise_rather_than_defaulting(self):
        image = ItemImageFactory()

        with mock.patch("apps.vision.images._fetch_info_dimensions", side_effect=OSError("timeout")):
            with pytest.raises(images.ImageUnavailable, match="Could not resolve dimensions"):
                images.dimensions(image)
