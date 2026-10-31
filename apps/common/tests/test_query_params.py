from django.http import QueryDict
import pytest

from apps.common.query_params import query_flag


@pytest.mark.parametrize("query", ["light=1", "light=true", "light=TRUE", "light=yes", "light= true "])
def test_a_true_spelling_sets_the_flag(query):
    assert query_flag(QueryDict(query), "light") is True


@pytest.mark.parametrize("query", ["", "light=", "light=0", "light=false", "light=no", "other=1"])
def test_anything_else_leaves_it_off(query):
    assert query_flag(QueryDict(query), "light") is False
