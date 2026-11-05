"""W1.1 by the letter models: which letters a page gets, and how they reach the review queue.

The HTR service is replaced at the HTTP call: its contract is pinned in
`apps/ml/tests/test_htr_letters_provider.py`, and the service itself in
`htr/selftest.py`. The page is 2,000 × 1,500 and is sent at half that width,
so every box the service returns is in pixels of a page half the size.
"""

import base64
import io
import json
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from PIL import Image
import pytest

from apps.annotations.models import GraphProposal
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.services.iiif import get_iiif_region_from_geojson
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.ml.models import MLJob
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory, CharacterFactory
from apps.vision import images
from apps.vision.services import letters
from apps.vision.services.letters import Letter

WIDTH, HEIGHT = 2000, 1500
SENT = 1000  # the width the service read the page at


def _letter(box=(0, 0, 10, 10), allograph_id=1, fit=0.9, probability=0.9) -> Letter:
    return Letter(box=box, allograph_id=allograph_id, fit=fit, probability=probability)


class TestChoose:
    def test_keeps_only_letters_whose_box_should_fit_and_whose_allograph_is_not_in_doubt(self):
        kept = _letter(box=(0, 0, 10, 10))
        loose = _letter(box=(20, 0, 10, 10), fit=0.59)
        doubtful = _letter(box=(40, 0, 10, 10), probability=0.69)

        assert letters.choose([kept, loose, doubtful]) == [kept]

    def test_proposes_a_few_of_each_allograph_the_likeliest_first(self):
        found = [_letter(box=(i * 20, 0, 10, 10), fit=0.6 + i / 100) for i in range(5)]
        other = _letter(box=(0, 50, 10, 10), allograph_id=2, fit=0.95, probability=0.95)

        chosen = letters.choose([*found, other], per_allograph=2)

        assert chosen == [other, found[4], found[3]]

    def test_proposes_nothing_inside_what_is_already_marked_or_proposed(self):
        marked = _letter(box=(100, 100, 20, 20))
        beside = _letter(box=(130, 100, 20, 20))

        assert letters.choose([marked, beside], marked=[(95, 95, 30, 30)]) == [beside]

    def test_one_letter_found_twice_is_proposed_once(self):
        better = _letter(box=(0, 0, 20, 20), fit=0.95)
        same = _letter(box=(2, 1, 20, 20), fit=0.8, allograph_id=2)

        assert letters.choose([same, better]) == [better]

    def test_stops_at_the_limit(self):
        found = [_letter(box=(i * 20, 0, 10, 10), allograph_id=i) for i in range(10)]

        assert len(letters.choose(found, limit=4)) == 4


def test_found_letters_are_put_in_the_page_s_pixels_and_unknown_allographs_counted():
    output = {
        "width": SENT,
        "letters": [
            {"box": [10, 20, 30, 40], "character": "s", "allograph": "long", "fit": 0.8, "probability": 0.9},
            {"box": [1, 1, 1, 1], "character": "þ", "allograph": "thorn", "fit": 0.8, "probability": 0.9},
        ],
    }

    found, unknown = letters.found_letters(output, width=WIDTH, ids={("s", "long"): 7})

    assert found == [Letter(box=(20.0, 40.0, 60.0, 80.0), allograph_id=7, fit=0.8, probability=0.9)]
    assert unknown == 1


def _jpeg(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (230, 220, 190)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _data_url(image, *, size):
    side = min(size, max(WIDTH, HEIGHT))
    scale = side / max(WIDTH, HEIGHT)
    return "data:image/jpeg;base64," + base64.b64encode(_jpeg(round(WIDTH * scale), round(HEIGHT * scale))).decode()


@pytest.fixture
def server():
    """The image server: the page's size, and the page at the size asked for."""
    with (
        mock.patch("apps.vision.images.dimensions", return_value=(WIDTH, HEIGHT)),
        mock.patch("apps.vision.images.data_url", side_effect=_data_url) as data_url,
    ):
        yield data_url


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = False
    settings.ML_DAILY_COST_CAP_MICROS = 0
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    settings.ML_HTR_URL = "http://htr:8080"
    return settings


@pytest.fixture
def taxonomy():
    s = CharacterFactory(name="s")
    return {
        "long_s": AllographFactory(character=s, name="long"),
        "round_s": AllographFactory(character=s, name="round"),
        "et": AllographFactory(character=CharacterFactory(name="7"), name="7"),
    }


def _found(box, character="s", allograph="long", fit=0.9, probability=0.95):
    return {
        "read": "s",
        "read_confidence": 0.9,
        "line": 0,
        "box": list(box),
        "fit": fit,
        "character": character,
        "allograph": allograph,
        "probability": probability,
    }


# In the sent page's pixels (half size): two long s, a round s, a Tironian et, and a doubtful one.
FOUND = [
    _found((100, 100, 20, 40)),
    _found((200, 100, 20, 40), fit=0.7),
    _found((300, 100, 20, 30), allograph="round", fit=0.8),
    _found((400, 100, 25, 25), character="7", allograph="7", fit=0.95),
    _found((500, 100, 20, 40), probability=0.4),
]


def _service(found=FOUND):
    body = {
        "model": "CATMuS Medieval 1.5.0",
        "revision": "d1c1" * 16,
        "letter_models": {"name": "letters", "revision": "7" * 64, "release": "local-2026-11-04"},
        "width": SENT,
        "height": 750,
        "letters": found,
    }
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return mock.patch("urllib.request.urlopen", return_value=response)


def _region(proposal: GraphProposal) -> tuple[float, ...]:
    region = get_iiif_region_from_geojson(json.dumps(proposal.annotation), image_height=HEIGHT)
    return tuple(round(float(v)) for v in region.split(","))


@pytest.mark.django_db
class TestProposePage:
    def test_files_the_likeliest_letters_in_the_page_s_pixels_as_proposals_of_one_ledger_job(
        self, server, enabled, taxonomy
    ):
        image = ItemImageFactory()
        hand = HandFactory(item_part=image.item_part)

        with _service() as urlopen:
            tally = letters.propose_page(image)

        sent = json.loads(urlopen.call_args.args[0].data)["image"]
        assert Image.open(io.BytesIO(base64.b64decode(sent))).size == (2000, 1500)  # under SEND_SIDE: as it is
        assert tally == {"proposed": 4, "found": 5, "unknown_allograph": 0, "refused": 0, "failed": 0, "unavailable": 0}
        proposals = list(GraphProposal.objects.order_by("-confidence"))
        job = MLJob.objects.get()
        assert [(_region(p), p.allograph, p.hand, p.ml_job, p.status) for p in proposals] == [
            ((800, 200, 50, 50), taxonomy["et"], hand, job, "pending"),
            ((200, 200, 40, 80), taxonomy["long_s"], hand, job, "pending"),
            ((600, 200, 40, 60), taxonomy["round_s"], hand, job, "pending"),
            ((400, 200, 40, 80), taxonomy["long_s"], hand, job, "pending"),
        ]
        assert [p.confidence for p in proposals] == pytest.approx([0.95 * 0.95, 0.9 * 0.95, 0.8 * 0.95, 0.7 * 0.95])
        assert (job.task, job.provider, job.model_version) == ("W1.1", "letters", "7" * 64)

    def test_does_not_propose_what_is_already_marked_or_proposed_on_the_page(self, server, enabled, taxonomy):
        image = ItemImageFactory()
        hand = HandFactory(item_part=image.item_part)
        mark = {"x": 195 / WIDTH, "y": 195 / HEIGHT, "w": 50 / WIDTH, "h": 90 / HEIGHT}
        GraphFactory(item_image=image, hand=hand, allograph=taxonomy["long_s"], annotation=images.ring_from_box(
            mark, width=WIDTH, height=HEIGHT
        ))  # fmt: skip

        with _service():
            letters.propose_page(image)
        with _service():
            again = letters.propose_page(image)

        assert GraphProposal.objects.count() == 3
        assert (200, 200, 40, 80) not in {_region(p) for p in GraphProposal.objects.all()}
        assert again["proposed"] == 0

    def test_a_page_whose_charter_has_no_hand_is_proposed_without_one(self, server, enabled, taxonomy):
        with _service():
            letters.propose_page(ItemImageFactory())

        assert set(GraphProposal.objects.values_list("hand", flat=True)) == {None}

    def test_files_nothing_while_inference_is_off(self, server, settings, taxonomy):
        settings.ML_INFERENCE_ENABLED = False

        with _service() as urlopen:
            tally = letters.propose_page(ItemImageFactory())

        assert tally["refused"] == 1
        urlopen.assert_not_called()
        assert not GraphProposal.objects.exists()

    def test_a_service_failure_files_nothing_and_the_ledger_says_why(self, server, enabled, taxonomy):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            tally = letters.propose_page(ItemImageFactory())

        assert tally["failed"] == 1
        assert MLJob.objects.get().status == MLJob.Status.FAILED
        assert not GraphProposal.objects.exists()

    def test_a_page_the_image_server_cannot_give_calls_no_model(self, enabled, taxonomy):
        with (
            mock.patch("apps.vision.images.dimensions", side_effect=images.ImageUnavailable("gone")),
            _service() as urlopen,
        ):
            tally = letters.propose_page(ItemImageFactory())

        assert tally["unavailable"] == 1
        urlopen.assert_not_called()
        assert not MLJob.objects.exists()


@pytest.mark.django_db
class TestRun:
    def test_works_through_the_pages_named_and_adds_up(self, server, enabled, taxonomy):
        pages = [ItemImageFactory(), ItemImageFactory()]

        with _service():
            tally = letters.run(selection=pages)

        assert (tally["selected"], tally["proposed"], tally["found"]) == (2, 8, 10)

    def test_stops_at_the_first_refusal(self, server, settings, taxonomy):
        settings.ML_INFERENCE_ENABLED = False

        tally = letters.run(selection=[ItemImageFactory(), ItemImageFactory()])

        assert (tally["selected"], tally["refused"]) == (1, 1)

    def test_the_command_proposes_on_the_pages_asked_for(self, server, enabled, taxonomy):
        image = ItemImageFactory()
        out = io.StringIO()

        with _service():
            call_command("propose_letters", "--image", str(image.pk), "--per-allograph", "1", stdout=out)

        assert "proposed: 3" in out.getvalue()
        assert "Nothing has entered the record." in out.getvalue()

    def test_the_command_refuses_a_page_that_does_not_exist(self):
        with pytest.raises(CommandError, match="No such image: 999999"):
            call_command("propose_letters", "--image", "999999")


@pytest.fixture
def release(tmp_path):
    root = tmp_path / "release"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"version": "test"}))
    (root / "splits.json").write_text(json.dumps({"by_charter": {"train": [], "held_out": []}}))
    return root


def _glyphs(root, rows):
    (root / "glyphs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.mark.django_db
class TestExportPages:
    def test_writes_each_annotated_page_as_the_service_is_sent_it_with_its_scale(self, server, release, tmp_path):
        located, unlocated = ItemImageFactory(), ItemImageFactory()
        _glyphs(
            release,
            [
                {"item_image_id": located.pk, "item_part_id": located.item_part_id, "iiif_region": "1,2,3,4"},
                {"item_image_id": located.pk, "item_part_id": located.item_part_id, "iiif_region": "5,6,7,8"},
                {"item_image_id": unlocated.pk, "item_part_id": unlocated.item_part_id, "iiif_region": None},
            ],
        )
        out = tmp_path / "pages"

        with mock.patch.object(letters, "SEND_SIDE", 1000):
            tally = letters.export_pages(release, out)

        assert tally == {"pages": 1, "exported": 1, "kept": 0, "unavailable": 0}
        assert json.loads((out / "pages.json").read_text()) == [
            {
                "item_image_id": located.pk,
                "item_part_id": located.item_part_id,
                "file": f"{located.pk}.jpg",
                "width": WIDTH,
                "height": HEIGHT,
                "scale": 0.5,
            }
        ]
        assert Image.open(out / f"{located.pk}.jpg").size == (1000, 750)

    def test_keeps_what_it_exported_and_retries_what_it_could_not(self, server, release, tmp_path):
        first, second = ItemImageFactory(), ItemImageFactory()
        _glyphs(
            release,
            [
                {"item_image_id": p.pk, "item_part_id": p.item_part_id, "iiif_region": "1,1,1,1"}
                for p in (first, second)
            ],
        )
        out = tmp_path / "pages"
        server.side_effect = [_data_url(None, size=4000), images.ImageUnavailable("timed out")]

        assert letters.export_pages(release, out)["unavailable"] == 1
        server.side_effect = _data_url
        assert letters.export_pages(release, out) == {"pages": 2, "exported": 1, "kept": 1, "unavailable": 0}
        assert len(json.loads((out / "pages.json").read_text())) == 2

    def test_the_command_refuses_what_is_not_a_release(self, tmp_path):
        with pytest.raises(CommandError, match="not a release"):
            call_command("export_letter_pages", "--release", str(tmp_path), "--out", str(tmp_path / "out"))
