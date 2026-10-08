from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest

from apps.manuscripts.tests.factories import ItemImageFactory, ItemPartFactory


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "factory"), [("item-parts", ItemPartFactory), ("item-images", ItemImageFactory)])
def test_paged_list_query_has_a_fixed_order(management_client, path, factory):
    factory()

    with CaptureQueriesContext(connection) as queries:
        management_client.get(f"/api/v1/manuscripts/management/{path}/", {"limit": 1})

    page_queries = [q["sql"] for q in queries.captured_queries if "LIMIT" in q["sql"]]
    assert len(page_queries) == 1
    assert "ORDER BY" in page_queries[0]
