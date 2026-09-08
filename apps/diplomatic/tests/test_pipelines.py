"""Selection, parsing and the vocabulary the parsers enforce.

The parsers are the boundary between a model's freedom and the database's
vocabulary, so they are tested as a gate rather than as a transformation: what
matters is not that a good answer survives, but that an inventive one does not.
"""

import pytest

from apps.diplomatic.models import CharterEntity, Formula, Relation
from apps.diplomatic.pipelines import curation, extraction, formulae, translation
from apps.diplomatic.pipelines.base import PIPELINE_REGISTRY, UnknownPipeline, resolve
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory


class TestRegistry:
    def test_every_phase_two_item_is_registered(self):
        assert set(PIPELINE_REGISTRY) == {"W2.1", "W2.2", "W2.4", "W3.2", "W3.3"}

    def test_an_unknown_key_names_the_ones_that_exist(self):
        with pytest.raises(UnknownPipeline, match="W2.1"):
            resolve("W9.9")


class TestPlainText:
    def test_tei_markup_is_stripped(self):
        assert extraction.plain_text("<p>Sciant <persName>David</persName></p>") == "Sciant David"

    def test_long_text_is_truncated_and_says_so(self):
        assert extraction.plain_text("x" * 20000).endswith("[…truncated]")


class TestEntityParsing:
    def test_a_role_outside_the_vocabulary_is_dropped(self):
        parsed = extraction.parse_entities(
            '{"entities": [{"role": "witness", "name": "Walterus"}, {"role": "chancellor", "name": "Nicholas"}]}'
        )
        assert [entity["name"] for entity in parsed["entities"]] == ["Walterus"]

    def test_a_fenced_answer_is_still_read(self):
        parsed = extraction.parse_entities('```json\n{"entities": [{"role": "place", "name": "Perth"}]}\n```')
        assert parsed["entities"][0]["name"] == "Perth"

    def test_an_answer_without_the_key_is_unusable(self):
        with pytest.raises(ValueError, match="entities"):
            extraction.parse_entities('{"people": []}')

    def test_prose_instead_of_json_is_unusable(self):
        with pytest.raises(ValueError, match="usable JSON"):
            extraction.parse_entities("Here are the entities I found:")


class TestTripleParsing:
    def test_an_invented_predicate_is_dropped(self):
        parsed = extraction.parse_triples(
            '{"triples": [{"subject": "a", "predicate": "witnessed_by", "object": "b"},'
            ' {"subject": "a", "predicate": "married_to", "object": "c"}]}'
        )
        assert len(parsed["triples"]) == 1

    def test_a_triple_missing_an_end_is_dropped(self):
        parsed = extraction.parse_triples('{"triples": [{"subject": "a", "predicate": "granted_by", "object": ""}]}')
        assert parsed["triples"] == []


class TestFormulaParsing:
    def test_an_unknown_kind_is_dropped(self):
        parsed = formulae.parse_formulae(
            '{"formulae": [{"kind": "sanctio", "label": "curse"}, {"kind": "preamble", "label": "x"}]}'
        )
        assert [item["kind"] for item in parsed["formulae"]] == ["sanctio"]

    def test_an_unrecognised_formula_keeps_an_empty_published_type(self):
        parsed = formulae.parse_formulae('{"formulae": [{"kind": "other", "label": "novel clause"}]}')
        assert parsed["formulae"][0]["published_type"] == ""


class TestVerdictParsing:
    def test_a_verdict_outside_the_three_is_unusable(self):
        with pytest.raises(ValueError, match="verdict"):
            curation.parse_verdict('{"verdict": "probably fine"}')

    def test_an_inconsistency_keeps_its_evidence(self):
        parsed = curation.parse_verdict(
            '{"verdict": "inconsistent", "evidence": "Nicholaus cancellarius", '
            '"reasoning": "died 1178", "suggested_range": "1165x1177"}'
        )
        assert parsed["evidence"] == "Nicholaus cancellarius"
        assert parsed["suggested_range"] == "1165x1177"


class TestTranslationParsing:
    def test_an_empty_translation_is_unusable(self):
        with pytest.raises(ValueError, match="no translation"):
            translation.parse_translation('{"translation": "   "}')


@pytest.mark.django_db
class TestSelection:
    def test_transcriptions_are_selected_and_empty_ones_are_not(self):
        ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant presentes")
        ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="   ")
        ImageTextFactory(type=ImageText.Type.TRANSLATION, content="Know all present")

        units = extraction.transcriptions()

        assert len(units) == 1
        assert units[0].context["text"] == "Sciant presentes"

    def test_only_the_untranslated_tail_is_selected(self):
        translated_image = ItemImageFactory()
        ImageTextFactory(item_image=translated_image, type=ImageText.Type.TRANSCRIPTION, content="Sciant")
        ImageTextFactory(item_image=translated_image, type=ImageText.Type.TRANSLATION, content="Know")
        lonely = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant presentes")

        units = translation.untranslated()

        assert [unit.source_id for unit in units] == [lonely.pk]

    def test_only_dated_charters_are_audited(self):
        dated = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant")
        undated = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant")
        item = undated.item_image.item_part.historical_item
        item.date = None
        item.save()

        units = curation.dated_charters()

        assert [unit.source_id for unit in units] == [dated.pk]
        assert units[0].context["date"]


@pytest.mark.django_db
class TestVocabularyMatchesTheDatabase:
    """The prompts quote these lists to the model; a drift is a silent bug."""

    def test_roles_and_predicates_come_from_the_models(self):
        assert extraction.ROLE_VALUES == list(CharterEntity.Role.values)
        assert extraction.PREDICATE_VALUES == list(Relation.Predicate.values)

    def test_formula_kinds_come_from_the_model(self):
        assert formulae.KIND_VALUES == list(Formula.Kind.values)
