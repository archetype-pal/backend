import pytest

from apps.common.tests.query_counts import assert_query_count_constant
from apps.symbols_structure.tests.factories import (
    AllographComponentFactory,
    AllographComponentFeatureFactory,
    AllographFactory,
    AllographPositionFactory,
)


@pytest.mark.django_db
def test_allograph_list_runs_a_fixed_number_of_queries(client):
    def add_rows(n: int) -> None:
        for _ in range(n):
            allograph = AllographFactory()
            component = AllographComponentFactory(allograph=allograph)
            AllographComponentFeatureFactory(allograph_component=component)
            AllographPositionFactory(allograph=allograph)

    assert_query_count_constant(client, "/api/v1/symbols_structure/allographs/", add_rows)
