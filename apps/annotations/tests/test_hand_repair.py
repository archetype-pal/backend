"""A6: graphs on another part's hand are moved only to a single same-name, same-scribe hand on the
image's part; everything else is listed, and nothing is written without --apply."""

from io import StringIO

from django.core.management import call_command
import pytest

from apps.annotations.models import Graph
from apps.annotations.services.hand_repair import (
    apply_graph_hand_repairs,
    clear_unmatched_hands,
    cross_part_attributions,
    graph_hand_breaches,
)
from apps.annotations.tests.factories import GraphFactory
from apps.common.models import EditEvent
from apps.manuscripts.tests.factories import ItemImageFactory, text_region
from apps.scribes.tests.factories import HandFactory, ScribeFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def corpus():
    placeholder = ScribeFactory(name="[name] update records relations later")
    stray = HandFactory(name="Main Hand", scribe=placeholder)

    matched = ItemImageFactory()
    own = HandFactory(name="Main Hand", scribe=placeholder, item_part=matched.item_part)
    other_scribe = ItemImageFactory()
    HandFactory(name="Main Hand", item_part=other_scribe.item_part)
    handless = ItemImageFactory()

    region = text_region(matched)
    region.hand = stray
    region.save()
    return {
        "stray": stray,
        "own": own,
        "repairable": [GraphFactory(item_image=matched, hand=stray), region],
        "review": [GraphFactory(item_image=other_scribe, hand=stray), GraphFactory(item_image=handless, hand=stray)],
        "fine": GraphFactory(item_image=matched, hand=own),
    }


def test_only_a_single_same_name_same_scribe_hand_is_proposed(corpus):
    breaches = {b.graph_id: b for b in graph_hand_breaches()}

    assert set(breaches) == {g.id for g in corpus["repairable"] + corpus["review"]}
    assert {g: b.to_hand_id for g, b in breaches.items()} == {
        **{g.id: corpus["own"].id for g in corpus["repairable"]},
        **{g.id: None for g in corpus["review"]},
    }
    assert breaches[corpus["review"][1].id].candidates == ()


def test_a_tick_on_another_parts_image_is_listed():
    hand = HandFactory()
    image = ItemImageFactory()
    hand.item_part_images.add(image, ItemImageFactory(item_part=hand.item_part))

    [tick] = cross_part_attributions()

    assert (tick.hand_id, tick.image_id) == (hand.id, image.id)


def test_the_command_writes_nothing_without_apply(corpus):
    out = StringIO()

    call_command("repair_graph_hands", stdout=out)

    assert set(Graph.objects.values_list("hand_id", flat=True)) == {corpus["stray"].id, corpus["own"].id}
    assert Graph.objects.filter(hand=corpus["stray"]).count() == 4
    assert "repairable (one hand on the image's part has the same name and scribe): 2" in out.getvalue()
    assert "left for review: 2" in out.getvalue()
    assert "Dry run" in out.getvalue()


def test_apply_moves_the_repairable_graphs_and_logs_each(corpus):
    events_before = EditEvent.objects.count()

    call_command("repair_graph_hands", "--apply", stdout=StringIO())

    moved = Graph.objects.filter(id__in=[g.id for g in corpus["repairable"]])
    assert set(moved.values_list("hand_id", flat=True)) == {corpus["own"].id}
    held = Graph.objects.filter(id__in=[g.id for g in corpus["review"]])
    assert set(held.values_list("hand_id", flat=True)) == {corpus["stray"].id}
    assert EditEvent.objects.count() == events_before + 2
    assert graph_hand_breaches() and all(b.to_hand_id is None for b in graph_hand_breaches())


def test_a_graph_whose_hand_changed_since_the_plan_is_left_alone(corpus):
    plan = graph_hand_breaches()
    changed = corpus["repairable"][0]
    Graph.objects.filter(pk=changed.pk).update(hand=HandFactory(item_part=changed.item_image.item_part))

    assert apply_graph_hand_repairs(plan) == 1


@pytest.fixture
def stray_regions(corpus):
    """A text and an editorial region with no hand on their own part to move to."""
    regions = []
    for kind in ("text", "editorial"):
        region = text_region(ItemImageFactory(), annotation_type=kind)
        region.hand = corpus["stray"]
        region.save()
        regions.append(region)
    return regions


def test_only_text_and_editorial_graphs_left_for_review_are_clearable(corpus, stray_regions):
    breaches = {b.graph_id: b for b in graph_hand_breaches()}

    assert {g for g, b in breaches.items() if b.clearable} == {g.id for g in stray_regions}


def test_the_clear_flag_writes_nothing_without_apply(corpus, stray_regions):
    out = StringIO()

    call_command("repair_graph_hands", "--clear-unmatched-text", stdout=out)

    assert Graph.objects.filter(hand=corpus["stray"]).count() == 6
    assert "of which text or editorial, to have the hand cleared: 2" in out.getvalue()
    assert "Dry run" in out.getvalue()


def test_apply_without_the_flag_clears_nothing(corpus, stray_regions):
    call_command("repair_graph_hands", "--apply", stdout=StringIO())

    assert set(Graph.objects.filter(id__in=[g.id for g in stray_regions]).values_list("hand_id", flat=True)) == {
        corpus["stray"].id
    }


def test_apply_with_the_flag_clears_the_regions_and_keeps_the_image_graphs(corpus, stray_regions):
    events_before = EditEvent.objects.count()
    out = StringIO()

    call_command("repair_graph_hands", "--apply", "--clear-unmatched-text", stdout=out)

    cleared = Graph.objects.filter(id__in=[g.id for g in stray_regions])
    assert set(cleared.values_list("hand_id", flat=True)) == {None}
    held = Graph.objects.filter(id__in=[g.id for g in corpus["review"]])
    assert set(held.values_list("hand_id", flat=True)) == {corpus["stray"].id}
    assert EditEvent.objects.count() == events_before + 4
    assert "Moved 2 graphs." in out.getvalue()
    assert "Cleared the hand on 2 graphs." in out.getvalue()


def test_a_region_whose_hand_changed_since_the_plan_is_not_cleared(corpus, stray_regions):
    plan = graph_hand_breaches()
    changed = stray_regions[0]
    own = HandFactory(item_part=changed.item_image.item_part)
    Graph.objects.filter(pk=changed.pk).update(hand=own)

    assert clear_unmatched_hands(plan) == 1
    assert Graph.objects.get(pk=changed.pk).hand_id == own.id
