"""Rolling back the place and description data migrations must not lose data."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import pytest

BEFORE_PLACE_FOLD = [("scribes", "0013_hand_place_ref")]
BEFORE_DESCRIPTION_FOLD = [("scribes", "0016_hand_description_model")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def _leaf():
    executor = MigrationExecutor(connection)
    return executor.loader.graph.leaf_nodes()


@pytest.fixture
def restore_schema():
    leaves = _leaf()
    yield
    _migrate(leaves)


def _make_hand(apps, **fields):
    Date = apps.get_model("common", "Date")
    Scribe = apps.get_model("scribes", "Scribe")
    ItemPart = apps.get_model("manuscripts", "ItemPart")
    HistoricalItem = apps.get_model("manuscripts", "HistoricalItem")
    Hand = apps.get_model("scribes", "Hand")
    historical_item = HistoricalItem.objects.create(type="Charter")
    item_part = ItemPart.objects.create(historical_item=historical_item)
    scribe = Scribe.objects.create(
        name="Scribe", period=Date.objects.create(date="s. xii", min_weight=1100, max_weight=1199)
    )
    return Hand.objects.create(name="Hand", scribe=scribe, item_part=item_part, **fields)


@pytest.mark.django_db(transaction=True)
def test_place_fold_round_trips(restore_schema):
    apps = _migrate(BEFORE_PLACE_FOLD)
    hand = _make_hand(apps, place="London")

    _migrate([("scribes", "0015_hand_place_to_fk")])
    apps = _migrate(BEFORE_PLACE_FOLD)

    assert apps.get_model("scribes", "Hand").objects.get(pk=hand.pk).place == "London"


@pytest.mark.django_db(transaction=True)
def test_description_fold_keeps_first_description_on_rollback(restore_schema):
    apps = _migrate([("scribes", "0018_remove_hand_description")])
    hand = _make_hand(apps)
    HandDescription = apps.get_model("scribes", "HandDescription")
    HandDescription.objects.create(hand_id=hand.pk, content="First")
    HandDescription.objects.create(hand_id=hand.pk, content="Second")

    apps = _migrate(BEFORE_DESCRIPTION_FOLD)

    assert apps.get_model("scribes", "Hand").objects.get(pk=hand.pk).description == "First"
