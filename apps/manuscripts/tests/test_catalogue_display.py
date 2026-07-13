import pytest

from apps.manuscripts.tests.factories import (
    BibliographicSourceFactory,
    CatalogueNumberFactory,
    HistoricalItemFactory,
)


@pytest.mark.django_db
def test_catalogue_numbers_display_prefixes_each_number_with_source_label():
    """A bare "236" is meaningless — it must be preceded by its (abbreviated) source."""
    historical_item = HistoricalItemFactory()
    ker = BibliographicSourceFactory(label="Ker")
    gneuss = BibliographicSourceFactory(label="Gneuss")
    CatalogueNumberFactory(historical_item=historical_item, catalogue=ker, number="236")
    CatalogueNumberFactory(historical_item=historical_item, catalogue=gneuss, number="12")

    display = historical_item.get_catalogue_numbers_display()

    assert "Ker 236" in display
    assert "Gneuss 12" in display
    # Numbers are never emitted without their source prefix.
    assert "236" not in display.replace("Ker 236", "")


@pytest.mark.django_db
def test_catalogue_numbers_display_empty_when_no_numbers():
    assert HistoricalItemFactory().get_catalogue_numbers_display() == ""
