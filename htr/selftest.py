"""Checks the reader against its baked model: `python -m unittest selftest`.

Not named `test_*.py`, so the backend's pytest does not collect it: it needs
Kraken and the model, which only this image has.
"""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request

from kraken.containers import BaselineLine, Segmentation
import letters
from PIL import Image, ImageDraw, ImageFont
import server
import torch
import train_letters

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
        self.assertEqual(self.request("/health"), (200, {**READER.describe(), "letter_models": None}))

    def test_without_letter_models_letters_are_unavailable(self):
        status, payload = self.request("/letters", json.dumps({"image": png(page([]))}).encode())

        self.assertEqual(status, 503)
        self.assertIn("No letter models are installed", payload["detail"])

    def test_reads_over_http(self):
        status, payload = self.request("/read", json.dumps({"image": png(page([]))}).encode())

        self.assertEqual(status, 200)
        self.assertEqual(payload, {**READER.describe(), "lines": []})

    def test_says_what_is_wrong(self):
        self.assertEqual(self.request("/read", b"{"), (400, {"detail": "The body is not JSON."}))
        self.assertEqual(self.request("/read", b"{}"), (400, {"detail": 'Send {"image": <base64 image>}.'}))
        self.assertEqual(self.request("/elsewhere", b"{}")[0], 404)
        self.assertEqual(self.request("/elsewhere")[0], 404)


# ---------------------------------------------------------------- letters (W1.1)

ALLOGRAPHS = [["s", "long"], ["s", "round"], ["7", "7"]]
ANSWER_KEYS = {"read", "read_confidence", "line", "box", "fit", "character", "allograph", "probability"}


def untrained_letter_models(directory: Path) -> None:
    """Letter models as `train_letters.py` writes them, with weights nobody trained."""
    torch.manual_seed(0)
    characters = {"<unknown>": 0, "s": 1, "e": 2}
    weights = directory / "letters.pt"
    torch.save(
        {
            "characters": characters,
            "allographs": ALLOGRAPHS,
            "box_model": letters.BoxModel(len(characters)).state_dict(),
            "classifier": letters.Classifier(len(characters), len(ALLOGRAPHS)).state_dict(),
        },
        weights,
    )
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    (directory / "letters.json").write_text(json.dumps({"name": "letters", "sha256": digest, "release": "test"}))


class LettersGeometryTest(unittest.TestCase):
    LINES = [
        {
            "text": "se e",
            "characters": [
                {"char": "s", "confidence": 0.9, "x": 100.0, "top": 50.0, "bottom": 90.0},
                {"char": "e\u0327", "confidence": 0.8, "x": 130.0, "top": 52.0, "bottom": 88.0},
                {"char": " ", "confidence": 0.99, "x": 150.0, "top": 50.0, "bottom": 90.0},
                {"char": "e", "confidence": 0.7, "x": 170.0, "top": 50.0, "bottom": 90.0},
            ],
        }
    ]

    def test_every_character_but_spaces_is_placed_with_its_neighbours_in_line_heights(self):
        found = letters.anchors(self.LINES)

        self.assertEqual([a.char for a in found], ["s", "e\u0327", "e"])
        s, cedilla, e = found
        self.assertEqual((s.x, s.y, s.line_height), (100.0, 70.0, 40.0))
        self.assertEqual(s.gaps, (1.0, 30 / 40, 0.0, 0.0))
        self.assertEqual(cedilla.gaps, (30 / 36, 20 / 36, 0.0, 1.0))
        self.assertEqual(e.gaps, (20 / 40, 1.0, 1.0, 0.0))
        # The models are told the letter, not its marks.
        self.assertEqual(cedilla.base, "e")

    def test_a_box_survives_the_window_both_ways(self):
        anchor = letters.anchors(self.LINES)[0]
        box = [90.0, 40.0, 25.0, 60.0]

        fractions = letters.box_to_window(box, anchor)

        self.assertEqual([round(v, 6) for v in letters.box_from_window(fractions, anchor)], box)
        # The window is four line-heights square, centred on the character.
        self.assertEqual(letters.box_to_window([20.0, -10.0, 160.0, 160.0], anchor), [0.0, 0.0, 1.0, 1.0])

    def test_a_large_page_is_read_smaller_and_placed_back_in_its_own_pixels(self):
        view, scale = letters.for_reading(Image.new("RGB", (5800, 2900)))
        self.assertEqual((view.size, scale), ((2900, 1450), 2.0))
        small = Image.new("RGB", (800, 600))
        self.assertEqual(letters.for_reading(small), (small, 1.0))


class LetterModelsTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        untrained_letter_models(self.directory)

    def test_finds_a_box_and_an_allograph_for_every_character(self):
        models = letters.LetterModels.load(self.directory)
        found = letters.anchors(LettersGeometryTest.LINES)

        answers = models.find(Image.new("L", (400, 200), 220), found)

        self.assertEqual(len(answers), 3)
        for answer, anchor in zip(answers, found, strict=True):
            self.assertEqual(answer["read"], anchor.char)
            self.assertEqual(len(answer["box"]), 4)
            self.assertGreater(answer["box"][2], 0)
            self.assertTrue(0 <= answer["fit"] <= 1 and 0 < answer["probability"] <= 1)
            self.assertIn([answer["character"], answer["allograph"]], ALLOGRAPHS)
        self.assertEqual(models.describe()["release"], "test")

    def test_will_not_load_weights_their_manifest_does_not_name(self):
        manifest = self.directory / "letters.json"
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), "sha256": "0" * 64}))

        with self.assertRaisesRegex(RuntimeError, "its manifest names"):
            letters.LetterModels.load(self.directory)

    def test_the_service_finds_letters_on_a_page_it_reads(self):
        reader = server.Reader(
            READER.model, name=READER.name, revision=READER.revision,
            letter_models=letters.LetterModels.load(self.directory),
        )  # fmt: skip

        payload = server.letters_request(reader, {"image": png(page(LINES))})

        self.assertEqual(payload["letter_models"], reader.describe_letters())
        self.assertEqual((payload["width"], payload["height"]), (800, 800))
        # Printed type: the reader finds most of its characters, and every one gets a box on the page.
        self.assertGreater(len(payload["letters"]), 40)
        for letter in payload["letters"]:
            self.assertEqual(set(letter), ANSWER_KEYS)


class TrainerScoreTest(unittest.TestCase):
    """What runs after the training, on weights nobody trained: a slip here costs the whole run."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        page(LINES).convert("RGB").save(self.directory / "1.jpg")
        self.characters = {"<unknown>": 0, "s": 1, "e": 2}
        self.allographs = {tuple(pair): i for i, pair in enumerate(ALLOGRAPHS)}
        self.args = argparse.Namespace(pages=str(self.directory), device="cpu")
        torch.manual_seed(0)
        self.box_model = letters.BoxModel(len(self.characters)).eval()
        self.classifier = letters.Classifier(len(self.characters), len(ALLOGRAPHS)).eval()

    def pages(self, split):
        found = letters.anchors(LettersGeometryTest.LINES)
        boxes = [{"box": [90.0, 50.0, 30.0, 40.0], "character": ALLOGRAPHS[0][0], "allograph": ALLOGRAPHS[0][1]}]
        pages = [{"split": split, "file": "1.jpg", "boxes": boxes, "anchors": found, "pairs": {0: 0}}]
        return [*pages, {**pages[0], "split": "train"}]

    def test_scores_the_held_out_charters_as_json(self):
        scores = train_letters.score(
            self.pages("test"), self.box_model, self.classifier, self.characters, self.allographs, self.args
        )

        self.assertEqual(scores["held_out_boxes"], 1)
        self.assertEqual(scores["read_inside"], 1)
        self.assertEqual(len(scores["box_by_fit"]), len(train_letters.THRESHOLDS))
        json.dumps(scores)


if __name__ == "__main__":
    unittest.main()
