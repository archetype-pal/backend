import json

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import pytest

KEY = "site_features.searchCategories.manuscripts.visibleColumns"
BEFORE = [("common", "0020_alter_editevent_action")]
AFTER = [("common", "0021_append_locus_column")]


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


def _store(apps, columns):
    apps.get_model("common", "AppSettings").objects.update_or_create(
        key=KEY, defaults={"value": json.dumps(columns), "is_public": True}
    )


def _stored(apps):
    return json.loads(apps.get_model("common", "AppSettings").objects.get(key=KEY).value)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("back_to_latest")
def test_locus_is_added_after_shelfmark_on_a_site_configured_before_it():
    _store(_migrate(BEFORE), ["Repository", "Shelfmark", "Images"])

    assert _stored(_migrate(AFTER)) == ["Repository", "Shelfmark", "Locus", "Images"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("back_to_latest")
def test_a_list_that_already_has_locus_is_left_alone():
    _store(_migrate(BEFORE), ["Locus", "Shelfmark"])

    assert _stored(_migrate(AFTER)) == ["Locus", "Shelfmark"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("back_to_latest")
def test_reversing_removes_locus():
    _store(_migrate(AFTER), ["Shelfmark", "Locus", "Images"])

    assert _stored(_migrate(BEFORE)) == ["Shelfmark", "Images"]
