from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import pytest

BEFORE = [("manuscripts", "0036_historicalitem_probable_text_date_dating_notes")]
AFTER = [("manuscripts", "0037_copy_date_assessments_to_historicalitem")]


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


def _item(apps, date=None):
    return apps.get_model("manuscripts", "HistoricalItem").objects.create(type="charter", date=date)


def _rows(apps):
    return sorted(
        (row.historical_item_id, row.date_id, row.probable_text_date, row.dating_notes)
        for row in apps.get_model("manuscripts", "HistoricalItemDateAssessment").objects.all()
    )


def _dating(apps):
    return {
        item.pk: (item.probable_text_date, item.dating_notes)
        for item in apps.get_model("manuscripts", "HistoricalItem").objects.all()
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("back_to_latest")
def test_the_dating_is_copied_onto_the_item_and_back():
    old = _migrate(BEFORE)
    Date = old.get_model("common", "Date")
    Assessment = old.get_model("manuscripts", "HistoricalItemDateAssessment")
    current = Date.objects.create(date="1140 x 1150", min_weight=1140, max_weight=1150)
    former = Date.objects.create(date="c. 1160", min_weight=1155, max_weight=1165)
    matching, stale, mixed, untouched, cleared = (_item(old, current) for _ in range(5))
    undated = _item(old)
    long_date = "x" * 100
    Assessment.objects.create(historical_item=matching, date=current, probable_text_date="1140s", dating_notes="Kept.")
    Assessment.objects.create(historical_item=stale, date=former, probable_text_date="c. 1160", dating_notes="Old.")
    Assessment.objects.create(historical_item=mixed, date=current, probable_text_date=long_date, dating_notes="Now.")
    Assessment.objects.create(historical_item=mixed, date=former, probable_text_date="", dating_notes="Before.")
    Assessment.objects.create(historical_item=cleared, date=current, probable_text_date="", dating_notes="Cleared.")
    Assessment.objects.create(historical_item=undated, date=former, probable_text_date="c. 1160", dating_notes="")
    rows_before = _rows(old)

    new = _migrate(AFTER)

    copied = _dating(new)
    assert copied[matching.pk] == ("1140s", "Kept.")
    assert copied[stale.pk] == ("", "c. 1160: Old.\nProbable text date: c. 1160")
    assert copied[mixed.pk] == (long_date, "Now.\n\nc. 1160: Before.")
    assert copied[untouched.pk] == ("", "")
    assert copied[cleared.pk] == ("", "Cleared.")
    assert copied[undated.pk] == ("", "c. 1160: Probable text date: c. 1160")
    assert _rows(new) == rows_before

    new.get_model("manuscripts", "HistoricalItem").objects.filter(pk=cleared.pk).update(dating_notes="")
    old = _migrate(BEFORE)

    assert _rows(old) == sorted(
        [
            (matching.pk, current.pk, "1140s", "Kept."),
            (stale.pk, current.pk, "", "c. 1160: Old.\nProbable text date: c. 1160"),
            (mixed.pk, current.pk, long_date, "Now.\n\nc. 1160: Before."),
            (undated.pk, former.pk, "c. 1160", ""),
        ]
    )

    again = _dating(_migrate(AFTER))
    assert again[mixed.pk] == (long_date, "Now.\n\nc. 1160: Before.")
    assert again[stale.pk] == ("", "c. 1160: Old.\nProbable text date: c. 1160")
    assert again[undated.pk] == ("", "c. 1160: Probable text date: c. 1160")
