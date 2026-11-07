"""The texts index facets a charter by who a scholar approved in each role (W2.1).

`test_registry_drift.py` already checks that the builder emits what the
registry declares and that `CharterEntity` is in the dependency map, and
`test_reindex_query_counts.py` that reading the entities costs no query per
text. These check what the facets hold, and that an approval reaches them.
"""

import pytest

from apps.diplomatic import services as diplomatic
from apps.diplomatic.models import CharterEntity, Proposal
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory
from apps.search.filter_contract import sanitize_filter_spec
from apps.search.registry import INDEX_REGISTRY, get_queryset_for_index
from apps.search.types import FilterSpec, IndexType
from apps.users.tests.factories import SuperuserFactory

pytestmark = pytest.mark.django_db

ROLE_FACETS = ("granters", "beneficiaries", "witnesses")


def _live_text(content: str = "<p>Dauid rex</p>") -> ImageText:
    return ImageTextFactory(content=content, status=ImageText.Status.LIVE)


def _entity(text: ImageText, role: str, name: str):
    return CharterEntity.objects.create(image_text=text, role=role, name=name)


def _document(text: ImageText) -> dict:
    """Built as a reindex builds it, through the registration's own queryset."""
    obj = get_queryset_for_index(IndexType.TEXTS).get(pk=text.pk)
    [document] = INDEX_REGISTRY[IndexType.TEXTS].documents(obj)
    return document


@pytest.fixture
def enqueued(monkeypatch, settings) -> list[tuple[str, list[int]]]:
    """Records `(segment, pks)` instead of queueing Celery tasks."""
    settings.SEARCH_AUTO_SYNC = True
    calls: list[tuple[str, list[int]]] = []
    monkeypatch.setattr(
        "apps.search.signals.sync_search_documents.delay",
        lambda segment, pks: calls.append((segment, sorted(pks))),
    )
    return calls


class TestDocument:
    def test_lists_who_was_approved_in_each_role_as_the_charter_writes_them(self):
        text = _live_text('<p><persName type="name">Dauid</persName> rex Scottorum</p>')
        _entity(text, CharterEntity.Role.GRANTER, "Dauid rex Scottorum")
        _entity(text, CharterEntity.Role.BENEFICIARY, "monachis de Kelchou")
        _entity(text, CharterEntity.Role.WITNESS, "Waltero filio Alani")
        _entity(text, CharterEntity.Role.WITNESS, "Hugone de Moreuilla")
        # Approved twice, from two proposals: one facet value.
        _entity(text, CharterEntity.Role.WITNESS, "Waltero filio Alani")

        document = _document(text)

        assert document["granters"] == ["Dauid rex Scottorum"]
        assert document["beneficiaries"] == ["monachis de Kelchou"]
        assert document["witnesses"] == ["Hugone de Moreuilla", "Waltero filio Alani"]
        # The markup's facet is untouched: it says who is named, not in what role.
        assert document["people"] == ["Dauid"]

    def test_a_place_date_or_transaction_is_no_ones_role(self):
        text = _live_text()
        _entity(text, CharterEntity.Role.PLACE, "Edenburgh")
        _entity(text, CharterEntity.Role.DATE, "1150")
        _entity(text, CharterEntity.Role.TRANSACTION, "grant")

        document = _document(text)

        assert {facet: document[facet] for facet in ROLE_FACETS} == {facet: [] for facet in ROLE_FACETS}

    def test_each_text_lists_only_its_own(self):
        face, other = _live_text(), _live_text()
        _entity(other, CharterEntity.Role.WITNESS, "Waltero filio Alani")

        assert _document(face)["witnesses"] == []
        assert _document(other)["witnesses"] == ["Waltero filio Alani"]


class TestIndex:
    @pytest.mark.parametrize("facet", ROLE_FACETS)
    def test_each_role_is_a_facet_a_search_can_filter_on(self, facet):
        registration = INDEX_REGISTRY[IndexType.TEXTS]
        spec = FilterSpec(facets={facet: ["Waltero filio Alani"]})

        assert facet in registration.default_facet_attributes
        # An attribute the index cannot filter on is dropped without a word.
        assert sanitize_filter_spec(spec, IndexType.TEXTS).facets == {facet: ["Waltero filio Alani"]}


class TestSync:
    def test_accepting_an_extraction_resyncs_its_text(self, enqueued, django_capture_on_commit_callbacks):
        text = _live_text()
        proposal = Proposal.objects.create(
            pipeline="W2.1",
            source_type="imagetext",
            source_id=text.pk,
            payload={"entities": [{"role": "witness", "name": "Waltero filio Alani", "normalised": "", "note": ""}]},
        )
        reviewer = SuperuserFactory()
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            diplomatic.accept(proposal, reviewer=reviewer)

        assert ("texts", [text.pk]) in enqueued

    def test_deleting_an_entity_resyncs_its_text(self, enqueued, django_capture_on_commit_callbacks):
        text = _live_text()
        entity = _entity(text, CharterEntity.Role.WITNESS, "Waltero filio Alani")
        enqueued.clear()

        with django_capture_on_commit_callbacks(execute=True):
            entity.delete()

        assert ("texts", [text.pk]) in enqueued
