"""0020 merges scripts that share a name, so 0021 can make the name unique."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import pytest

BEFORE = [("scribes", "0019_hand_display_order")]
AFTER = [("scribes", "0021_script_name_unique")]


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
def test_hands_move_to_the_lowest_pk_and_the_duplicate_goes():
    old = _migrate(BEFORE)
    Script = old.get_model("scribes", "Script")
    Hand = old.get_model("scribes", "Hand")
    Scribe = old.get_model("scribes", "Scribe")
    ItemPart = old.get_model("manuscripts", "ItemPart")
    HistoricalItem = old.get_model("manuscripts", "HistoricalItem")
    kept, duplicate, other = (Script.objects.create(name=name) for name in ("Caroline", "Caroline", "Square"))
    part = ItemPart.objects.create(historical_item=HistoricalItem.objects.create(type="Charter"))
    hand = Hand.objects.create(item_part=part, scribe=Scribe.objects.create(name="S"), name="H", script=duplicate)
    other_hand = Hand.objects.create(item_part=part, scribe=hand.scribe, name="I", script=other)

    new = _migrate(AFTER)

    assert sorted(new.get_model("scribes", "Script").objects.values_list("pk", flat=True)) == [kept.pk, other.pk]
    NewHand = new.get_model("scribes", "Hand")
    assert NewHand.objects.get(pk=hand.pk).script_id == kept.pk
    assert NewHand.objects.get(pk=other_hand.pk).script_id == other.pk
