"""0019 numbers each part's hands in the order the three old columns gave them."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import pytest

BEFORE = [("scribes", "0018_remove_hand_description")]
AFTER = [("scribes", "0019_hand_display_order")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def back_to_latest():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("back_to_latest")
def test_each_parts_hands_are_numbered_in_their_old_order():
    old = _migrate(BEFORE)
    Hand = old.get_model("scribes", "Hand")
    Scribe = old.get_model("scribes", "Scribe")
    ItemPart = old.get_model("manuscripts", "ItemPart")
    HistoricalItem = old.get_model("manuscripts", "HistoricalItem")
    scribe = Scribe.objects.create(name="S")

    def part():
        return ItemPart.objects.create(historical_item=HistoricalItem.objects.create(type="Charter"))

    one, two = part(), part()
    hands = {
        "default": Hand.objects.create(item_part=one, scribe=scribe, name="D", num=100, is_default=True),
        "preferred": Hand.objects.create(item_part=one, scribe=scribe, name="C", num=99, priority=10),
        "low num": Hand.objects.create(item_part=one, scribe=scribe, name="B", num=1),
        "high num": Hand.objects.create(item_part=one, scribe=scribe, name="A", num=2),
        "alone": Hand.objects.create(item_part=two, scribe=scribe, name="E", num=7),
    }

    new = _migrate(AFTER)

    order = dict(new.get_model("scribes", "Hand").objects.values_list("id", "display_order"))
    assert {name: order[hand.id] for name, hand in hands.items()} == {
        "default": 1,
        "preferred": 2,
        "low num": 3,
        "high num": 4,
        "alone": 1,
    }
