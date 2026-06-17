from unittest.mock import MagicMock

from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.types import IndexType


class TestApplyIndexSettings:
    def test_disables_typo_tolerance_on_numbers(self):
        writer = MeilisearchIndexWriter()
        writer._client = MagicMock()
        index = writer._client.index.return_value

        writer._apply_index_settings("texts", IndexType.TEXTS)

        # Dates/shelfmark numbers must match exactly, not fuzzily.
        index.update_typo_tolerance.assert_called_once_with({"disableOnNumbers": True})
        # The other settings are still applied alongside it.
        index.update_searchable_attributes.assert_called_once()
        index.update_filterable_attributes.assert_called_once()
        index.update_pagination_settings.assert_called_once()
