"""Checks the embedder against its baked weights: `python -m unittest selftest`.

Not named `test_*.py`, so the backend's pytest does not collect it: it needs
torch and the weights, which only this image has.
"""

import base64
import io
import json
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request

from PIL import Image, ImageDraw
import server
import torch


def png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def glyph(shape: str, *, width: int = 40, height: int = 60, stroke: int = 5) -> Image.Image:
    """A dark stroke on parchment: a ring, or an upright bar."""
    image = Image.new("RGB", (width, height), (232, 220, 190))
    draw = ImageDraw.Draw(image)
    if shape == "ring":
        draw.ellipse((6, 10, width - 6, height - 10), outline=(40, 30, 20), width=stroke)
    else:
        draw.rectangle((width // 2 - stroke // 2, 6, width // 2 + stroke // 2, height - 6), fill=(40, 30, 20))
    return image


ENCODER = server.Encoder.load()


class FitTest(unittest.TestCase):
    def test_scales_to_fit_and_pads_in_the_edge_colour_with_the_glyph_centred(self):
        image = glyph("bar", width=20, height=60)

        fitted = server.fit(image)

        self.assertEqual(fitted.size, (server.SIZE, server.SIZE))
        self.assertEqual(fitted.getpixel((0, 0)), (232, 220, 190))
        self.assertEqual(fitted.getpixel((server.SIZE // 2, server.SIZE // 2)), (40, 30, 20))

    def test_keeps_the_glyph_s_proportions(self):
        fitted = server.fit(glyph("bar", width=20, height=60))
        # The crop becomes 128 x 384, centred: parchment either side of it.
        self.assertEqual(fitted.getpixel((server.SIZE // 2 - 70, server.SIZE // 2)), (232, 220, 190))


class RequestTest(unittest.TestCase):
    def test_refuses_what_it_cannot_embed(self):
        cases = [
            (None, "Send"),
            ({"images": []}, "No images"),
            ({"images": [png(glyph("ring"))] * (server.MAX_IMAGES + 1)}, "at most"),
            ({"images": [42]}, "not a base64 string"),
            ({"images": ["not base64!"]}, "not a PNG or JPEG"),
            ({"images": [base64.b64encode(b"plain text").decode()]}, "not a PNG or JPEG"),
            ({"images": [png(Image.new("RGB", (server.MAX_SIDE + 1, 10)))]}, "at most 1024px"),
        ]
        for body, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(server.BadRequest, message):
                server.embed_request(ENCODER, body)


class EncoderTest(unittest.TestCase):
    def test_names_the_pinned_weights(self):
        self.assertEqual(
            ENCODER.describe(),
            {"model": "LaMOP/TrOCR_Manicule_2026_Latin_Medieval", "revision": server.REVISION, "dimensions": 768},
        )

    def test_will_not_run_an_encoder_from_another_checkpoint(self):
        with (
            mock.patch.object(server, "REVISION", "0" * 40),
            self.assertRaisesRegex(RuntimeError, "rebuild the image"),
        ):
            server.Encoder.load()

    def test_one_unit_vector_per_image_in_order_and_the_same_for_the_same_glyph(self):
        ring, bar = glyph("ring"), glyph("bar")

        vectors = ENCODER.embed([ring, bar, ring])
        reversed_vectors = ENCODER.embed([bar, ring])

        self.assertEqual([len(vector) for vector in vectors], [768, 768, 768])
        for vector in vectors:
            self.assertAlmostEqual(float(torch.tensor(vector).norm()), 1.0, places=4)
        self.assertEqual(vectors[0], vectors[2])
        self.assertEqual(reversed_vectors, [vectors[1], vectors[0]])

    def test_batches_past_one_forward_pass(self):
        rings = [glyph("ring", stroke=stroke) for stroke in range(1, server.BATCH + 3)]
        vectors = ENCODER.embed(rings)
        self.assertEqual(len(vectors), server.BATCH + 2)

    def test_a_glyph_is_nearer_a_variant_of_itself_than_a_different_shape(self):
        vectors = ENCODER.embed([glyph("ring"), glyph("ring", stroke=7), glyph("bar")])
        ring, heavier_ring, bar = (torch.tensor(vector) for vector in vectors)
        self.assertGreater(float(ring @ heavier_ring), float(ring @ bar))


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(ENCODER))
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
        self.assertEqual(self.request("/health"), (200, ENCODER.describe()))

    def test_embeds_over_http(self):
        status, payload = self.request("/embed", json.dumps({"images": [png(glyph("ring"))]}).encode())

        self.assertEqual(status, 200)
        self.assertEqual(payload["dimensions"], 768)
        self.assertEqual(payload["vectors"], ENCODER.embed([glyph("ring")]))

    def test_says_what_is_wrong(self):
        self.assertEqual(self.request("/embed", b"{"), (400, {"detail": "The body is not JSON."}))
        self.assertEqual(self.request("/embed", b'{"images": []}'), (400, {"detail": "No images to embed."}))
        self.assertEqual(self.request("/elsewhere", b"{}")[0], 404)
        self.assertEqual(self.request("/elsewhere")[0], 404)


if __name__ == "__main__":
    unittest.main()
