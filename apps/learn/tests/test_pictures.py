"""The picture a lesson is about: what is accepted, how it is brought to size, and the closer looks."""

import base64
import io
from unittest import mock

from PIL import Image
import pytest

from apps.learn.services import pictures
from apps.vision import images

from .conftest import jpeg


def _size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
    return width, height


class TestFromUpload:
    def test_a_picture_is_kept_as_a_jpeg_at_its_size(self):
        picture = pictures.from_upload(jpeg(800, 600))

        assert (picture.width, picture.height) == (800, 600)
        assert _size(picture.jpeg) == (800, 600)
        assert picture.jpeg[:3] == b"\xff\xd8\xff"

    def test_a_large_picture_is_brought_to_the_longest_side_the_model_reads(self):
        picture = pictures.from_upload(jpeg(5152, 2000))

        assert picture.width == pictures.LONGEST_SIDE
        assert picture.height == round(2000 * pictures.LONGEST_SIDE / 5152)
        assert _size(picture.jpeg) == (picture.width, picture.height)

    def test_a_picture_is_turned_upright_from_its_camera_orientation(self):
        # Orientation 6: the camera was turned; the stored pixels need a quarter turn.
        picture = pictures.from_upload(jpeg(800, 600, exif_orientation=6))

        assert (picture.width, picture.height) == (600, 800)

    @pytest.mark.parametrize("fmt", ["PNG", "WEBP", "TIFF"])
    def test_other_picture_formats_are_accepted(self, fmt):
        assert pictures.from_upload(jpeg(300, 200, fmt=fmt)).width == 300

    def test_a_picture_with_transparency_becomes_rgb(self):
        picture = pictures.from_upload(jpeg(300, 200, fmt="PNG", mode="RGBA"))

        with Image.open(io.BytesIO(picture.jpeg)) as image:
            assert image.mode == "RGB"

    def test_an_empty_file_is_refused(self):
        with pytest.raises(pictures.PictureRefused, match="empty"):
            pictures.from_upload(b"")

    def test_a_file_over_the_size_limit_is_refused_before_it_is_read(self):
        with pytest.raises(pictures.PictureRefused, match="15 MB"):
            pictures.from_upload(b"\xff" * (pictures.MAX_UPLOAD_BYTES + 1))

    def test_a_file_that_is_not_a_picture_is_refused(self):
        with pytest.raises(pictures.PictureRefused, match="not a picture"):
            pictures.from_upload(b"%PDF-1.7 not a picture")

    def test_a_format_outside_the_accepted_ones_is_refused(self):
        with pytest.raises(pictures.PictureRefused, match="JPEG, PNG, WebP or TIFF"):
            pictures.from_upload(jpeg(100, 100, fmt="GIF"))

    def test_a_picture_with_too_many_pixels_is_refused_before_it_is_decoded(self, monkeypatch):
        monkeypatch.setattr(pictures, "MAX_UPLOAD_PIXELS", 100 * 100)

        with pytest.raises(pictures.PictureRefused, match="too many pixels"):
            pictures.from_upload(jpeg(101, 100))
        assert pictures.from_upload(jpeg(100, 100)).width == 100


class TestFromPage:
    def test_a_corpus_page_is_its_rendition_at_the_longest_side(self):
        data = jpeg(1800, 2576)
        url = "data:image/jpeg;base64," + base64.b64encode(data).decode()
        page = mock.Mock(pk=7)

        with mock.patch.object(images, "data_url", return_value=url) as fetch:
            picture = pictures.from_page(page)

        fetch.assert_called_once_with(page, size=pictures.LONGEST_SIDE)
        assert picture.jpeg == data
        assert (picture.width, picture.height) == (1800, 2576)

    def test_a_page_that_does_not_come_back_as_a_picture_is_unavailable(self):
        url = "data:image/jpeg;base64," + base64.b64encode(b"<html>error</html>").decode()

        with mock.patch.object(images, "data_url", return_value=url), pytest.raises(images.ImageUnavailable):
            pictures.from_page(mock.Mock(pk=7))


class TestClamp:
    def test_a_box_on_the_picture_is_kept_in_whole_pixels(self):
        assert pictures.clamp({"x": 10.4, "y": 20.6, "width": 30, "height": 40}, width=800, height=600) == {
            "x": 10,
            "y": 21,
            "width": 30,
            "height": 40,
        }

    def test_a_box_over_the_edge_is_cut_at_it(self):
        assert pictures.clamp({"x": 780, "y": -10, "width": 50, "height": 30}, width=800, height=600) == {
            "x": 780,
            "y": 0,
            "width": 20,
            "height": 20,
        }

    @pytest.mark.parametrize(
        "box",
        [
            {"x": 900, "y": 10, "width": 50, "height": 50},
            {"x": 10, "y": 10, "width": 0, "height": 50},
            # Fractions of the picture rather than pixels round to nothing.
            {"x": 0.2, "y": 0.3, "width": 0.05, "height": 0.02},
            {"x": "left", "y": 0, "width": 5, "height": 5},
            {"x": 1, "y": 1},
        ],
    )
    def test_a_box_with_nothing_on_the_picture_is_none(self, box):
        assert pictures.clamp(box, width=800, height=600) is None


class TestCloserLook:
    def test_a_region_is_enlarged_until_its_longer_side_is_the_closer_look_side(self):
        data, scale = pictures.closer_look(jpeg(), {"x": 0, "y": 0, "width": 700, "height": 350})

        assert scale == round(pictures.CLOSER_LOOK_SIDE / 700, 2)
        assert _size(data) == (pictures.CLOSER_LOOK_SIDE, pictures.CLOSER_LOOK_SIDE // 2)

    def test_a_small_region_is_enlarged_no_more_than_four_times(self):
        data, scale = pictures.closer_look(jpeg(), {"x": 0, "y": 0, "width": 50, "height": 20})

        assert scale == pictures.MAX_ENLARGEMENT
        assert _size(data) == (200, 80)

    def test_a_region_larger_than_the_closer_look_is_not_shrunk(self):
        data, scale = pictures.closer_look(jpeg(2000, 1000), {"x": 0, "y": 0, "width": 2000, "height": 1000})

        assert scale == 1.0
        assert _size(data) == (2000, 1000)

    def test_the_enlargement_is_of_the_region_asked_for(self):
        # The picture's dark bar is at its top left: a look there is dark, a look elsewhere is not.
        dark, _ = pictures.closer_look(jpeg(), {"x": 0, "y": 0, "width": 100, "height": 50})
        light, _ = pictures.closer_look(jpeg(), {"x": 600, "y": 400, "width": 100, "height": 50})

        with Image.open(io.BytesIO(dark)) as image:
            assert image.convert("L").getpixel((10, 10)) < 50
        with Image.open(io.BytesIO(light)) as image:
            assert image.convert("L").getpixel((10, 10)) > 200

    def test_a_sliver_is_widened_to_something_that_can_be_seen(self):
        data, _ = pictures.closer_look(jpeg(), {"x": 10, "y": 10, "width": 1, "height": 1})

        assert min(_size(data)) >= pictures.SMALLEST_LOOK
