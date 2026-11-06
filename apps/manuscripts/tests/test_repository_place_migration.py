"""0033 links each repository's place text to the place list."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import pytest

BEFORE = [("manuscripts", "0032_repository_place_ref")]
AFTER = [("manuscripts", "0033_copy_repository_place_to_place_ref")]


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
def test_names_differing_by_case_share_a_place_and_blanks_get_none():
    old = _migrate(BEFORE)
    Repository = old.get_model("manuscripts", "Repository")
    existing = old.get_model("common", "Place").objects.create(name="Glasgow")
    other_case = Repository.objects.create(name="A", label="A", place="glasgow")
    new_one, same_new = (Repository.objects.create(name=n, label=n, place=p) for n, p in (("B", "Ayr"), ("C", " AYR ")))
    blank, spaces = (Repository.objects.create(name=n, label=n, place=p) for n, p in (("D", ""), ("E", "  ")))

    new = _migrate(AFTER)

    NewRepository = new.get_model("manuscripts", "Repository")
    place_ref = {row.pk: row.place_ref_id for row in NewRepository.objects.all()}
    assert place_ref[other_case.pk] == existing.pk
    assert place_ref[new_one.pk] is not None
    assert place_ref[new_one.pk] == place_ref[same_new.pk]
    assert place_ref[blank.pk] is None
    assert place_ref[spaces.pk] is None
    assert new.get_model("common", "Place").objects.filter(name__iexact="ayr").count() == 1
