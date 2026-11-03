"""The corpus dating audit — ROADMAP Track H; AI programme W4.1 precondition.

The audit exists to find datings that cannot be true, and to say plainly that
without recorded provenance a date-from-script model would learn the
palaeographer's judgement and report it back as a discovery.
"""

from io import StringIO

from django.core.management import call_command
import pytest

from apps.common.models import Date
from apps.manuscripts.services import dating


def _date(label: str, low: int, high: int) -> Date:
    date: Date = Date.objects.create(date=label, min_weight=low, max_weight=high)
    return date


@pytest.mark.django_db
class TestFindsWhatCannotBeTrue:
    def test_an_inverted_range_is_caught(self):
        _date("prob. × 1212, prob. ca. 1196×", 1212, 1196)

        problems = dating.run().by_kind("inverted")

        assert len(problems) == 1
        assert "1212" in problems[0].detail

    def test_a_zero_bound_is_not_year_zero(self):
        """It sorts to the front of every ordered query that uses it."""
        _date("early", 0, 0)

        assert len(dating.run().by_kind("unbounded")) == 1

    def test_a_date_outside_the_corpus_period_is_caught(self):
        _date("1867", 1867, 1867)

        assert len(dating.run().by_kind("out_of_era")) == 1

    def test_a_label_naming_years_outside_its_bounds_is_caught(self):
        """The label is what a scholar wrote; the bounds are what a model reads."""
        _date("22/Jun, 1205 × 1214; perhaps 22/Jun/1210", 1205, 1210)

        problems = dating.run().by_kind("label_disagrees")

        assert len(problems) == 1
        assert "1214" in problems[0].detail

    def test_a_sound_dating_raises_nothing(self):
        _date("1189 × 1195", 1189, 1195)

        assert dating.run().problems == []

    def test_a_label_with_no_year_is_not_a_disagreement(self):
        _date("temp. William I", 1165, 1214)

        assert dating.run().by_kind("label_disagrees") == []


@pytest.mark.django_db
class TestUsability:
    def test_broken_datings_are_excluded_from_the_usable_count(self):
        _date("1189 × 1195", 1189, 1195)
        _date("early", 0, 0)
        _date("inverted", 1212, 1196)

        audit = dating.run()

        assert audit.dates == 3
        assert audit.usable_for_training == 1

    def test_a_label_disagreement_does_not_make_a_dating_unusable(self):
        """The bounds are still sound; it is the label that needs a human."""
        _date("1205 × 1214; perhaps 1210", 1205, 1210)

        assert dating.run().usable_for_training == 1


@pytest.mark.django_db
class TestProvenance:
    def test_reports_that_nothing_records_its_provenance(self):
        _date("1189 × 1195", 1189, 1195)

        assert dating.run().provenance_recorded == 0


@pytest.mark.django_db
class TestCommand:
    def _run(self, **kwargs) -> str:
        out = StringIO()
        call_command("date_audit", stdout=out, **kwargs)
        return out.getvalue()

    def test_names_the_circularity_W4_1_would_otherwise_have(self):
        _date("1189 × 1195", 1189, 1195)

        output = self._run()

        assert "No dating records its provenance" in output
        assert "report it back as a discovery" in output

    def test_reports_each_problem_with_its_label(self):
        _date("prob. × 1212, prob. ca. 1196×", 1212, 1196)

        output = self._run()

        assert "cannot be true" in output
        assert "1196" in output

    def test_strict_exits_non_zero_on_an_unusable_dating(self):
        _date("early", 0, 0)

        with pytest.raises(SystemExit):
            self._run(strict=True)

    def test_strict_passes_a_clean_corpus(self):
        _date("1189 × 1195", 1189, 1195)

        assert "Every dating is internally consistent." in self._run(strict=True)
