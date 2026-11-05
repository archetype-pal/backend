"""Checks the reader against its baked model: `python -m unittest selftest`.

Not named `test_*.py`, so the backend's pytest does not collect it: it needs
Kraken and the model, which only this image has.
"""

import base64
import io
import json
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request

from kraken.containers import BaselineLine, Segmentation
from PIL import Image, ImageDraw, ImageFont
import server

LINES = ["Omnibus probis hominibus", "tocius terre sue salutem", "sciant presentes et futuri"]


def png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# Each line is written 70 pixels below the last, in 32-pixel type whose baseline is 26 pixels below its top.
SPACING, SIZE, BASELINE = 70, 32, 26


def page(lines: list[str]) -> Image.Image:
    """Dark writing on parchment, one line under another, on a page as square as a charter's.

    The segmenter scales every page to one height, so a short, wide page would
    cost it several times the memory a real one does.
    """
    image = Image.new("RGB", (800, 800), (232, 220, 190))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=SIZE)
    for number, line in enumerate(lines):
        draw.text((60, 60 + SPACING * number), line, fill=(40, 30, 20), font=font)
    return image


def written_where(lines: list[str]) -> Segmentation:
    """Where `page` wrote each line, as a segmenter would report it."""
    found = []
    for number in range(len(lines)):
        top = 60 + SPACING * number
        found.append(
            BaselineLine(
                id=f"line-{number}",
                baseline=[(60, top + BASELINE), (740, top + BASELINE)],
                boundary=[(56, top - 4), (744, top - 4), (744, top + SIZE + 6), (56, top + SIZE + 6)],
            )
        )
    return Segmentation(
        type="baselines", imagename="", text_direction="horizontal-lr", script_detection=False, lines=found
    )


def distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        current = [i]
        for j, y in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


READER = server.Reader.load()


class RequestTest(unittest.TestCase):
    def test_refuses_what_it_cannot_read(self):
        cases = [
            (None, "Send"),
            ({"images": []}, "Send"),
            ({"image": 42}, "not a base64 string"),
            ({"image": "not base64!"}, "not a PNG or JPEG"),
            ({"image": base64.b64encode(b"plain text").decode()}, "not a PNG or JPEG"),
            ({"image": png(Image.new("RGB", (server.MAX_SIDE + 1, 10)))}, "at most 4000px"),
        ]
        for body, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(server.BadRequest, message):
                server.read_request(READER, body)


class ReaderTest(unittest.TestCase):
    def test_names_the_pinned_model(self):
        self.assertEqual(
            READER.describe(),
            {"model": "CATMuS Medieval 1.5.0", "revision": server.MODEL_SHA256, "segmenter": "kraken blla"},
        )

    def test_will_not_run_a_model_with_another_digest(self):
        with (
            mock.patch.object(server, "MODEL_SHA256", "0" * 64),
            self.assertRaisesRegex(RuntimeError, "rebuild the image"),
        ):
            server.Reader.load()

    def test_will_not_run_unpinned(self):
        with mock.patch.object(server, "MODEL_SHA256", ""), self.assertRaisesRegex(RuntimeError, "unpinned"):
            server.Reader.load()

    def test_reads_each_line_it_is_shown_with_its_box(self):
        lines = READER.recognise(page(LINES), written_where(LINES))

        self.assertEqual(len(lines), len(LINES))
        for number, (line, written) in enumerate(zip(lines, LINES, strict=True)):
            with self.subTest(written=written):
                # Printed type is not what the model was trained on; the reading must still be close.
                self.assertLess(distance(line["text"], written) / len(written), 0.3, line["text"])
                self.assertEqual(line["box"], [56, 56 + SPACING * number, 688, SIZE + 10])

    def test_finds_the_lines_of_a_page_itself_top_to_bottom(self):
        written = page(LINES)

        lines = READER.read(written)

        # The segmenter was trained on manuscripts and may split printed type into pieces; it must
        # still find writing, in order down the page, inside the page, every line with a reading.
        self.assertGreaterEqual(len(lines), len(LINES))
        middles = [line["box"][1] + line["box"][3] / 2 for line in lines]
        self.assertLess(middles[0], 60 + SPACING)
        self.assertGreater(middles[-1], 60 + SPACING * 2)
        for line in lines:
            x, y, width, height = line["box"]
            self.assertTrue(line["text"])
            self.assertTrue(0 <= x <= x + width <= written.width and 0 <= y <= y + height <= written.height)

    def test_a_blank_page_has_no_lines(self):
        self.assertEqual(READER.read(page([])), [])


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(READER))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path: str, body: bytes | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(self.base + path, data=body, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_health_names_the_model(self):
        self.assertEqual(self.request("/health"), (200, READER.describe()))

    def test_reads_over_http(self):
        status, payload = self.request("/read", json.dumps({"image": png(page([]))}).encode())

        self.assertEqual(status, 200)
        self.assertEqual(payload, {**READER.describe(), "lines": []})

    def test_says_what_is_wrong(self):
        self.assertEqual(self.request("/read", b"{"), (400, {"detail": "The body is not JSON."}))
        self.assertEqual(self.request("/read", b"{}"), (400, {"detail": 'Send {"image": <base64 image>}.'}))
        self.assertEqual(self.request("/elsewhere", b"{}")[0], 404)
        self.assertEqual(self.request("/elsewhere")[0], 404)


if __name__ == "__main__":
    unittest.main()
