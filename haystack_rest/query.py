import operator
import warnings
from functools import reduce
from itertools import chain

from haystack_rest import constants
from haystack_rest.utils import merge_dict


class BaseQueryBuilder:
    """
    Query builder base class.
    """

    def __init__(self, backend, view):
        self.backend = backend
        self.view = view

    def build_query(self, **filters):
        """
        :param dict[str, list[str]] filters: is an expanded QueryDict or
          a mapping of keys to a list of parameters.
        """
        raise NotImplementedError("You should override this method in subclasses.")

    @staticmethod
    def tokenize(stream, separator):
        """
        Tokenize and yield query parameter values.

        :param stream: Input value
        :param separator: Character to use to separate the tokens.
        :return:
        """
        for value in stream:
            for token in value.split(separator):
                if token:
                    yield token.strip()


class FilterQueryBuilder(BaseQueryBuilder):
    """
    Query builder class suitable for doing basic filtering.
    """

    def __init__(self, backend, view):
        super().__init__(backend, view)

        assert getattr(self.backend, "default_operator", None) in (
            operator.and_,
            operator.or_,
        ), f"{self.backend.__class__.__name__}.default_operator must be either 'operator.and_' or 'operator.or_'."
        self.default_operator = self.backend.default_operator
        self.default_same_param_operator = getattr(self.backend, "default_same_param_operator", self.default_operator)

    def get_same_param_operator(self, param):
        """
        Helper method to allow per param configuration of which operator should be used when multiple filters for the
        same param are found.

        :param str param: is the param for which you want to get the operator
        :return: Either operator.or_ or operator.and_
        """
        return self.default_same_param_operator

    def build_query(self, **filters):
        """
        Creates a single SQ filter from querystring parameters that correspond to the SearchIndex fields
        that have been "registered" in `view.fields`.

        Default behavior is to `OR` terms for the same parameters, and `AND` between parameters. Any
        querystring parameters that are not registered in `view.fields` will be ignored.

        :param dict[str, list[str]] filters: is an expanded QueryDict or a mapping of keys to a list of
        parameters.
        """

        applicable_filters = []
        applicable_exclusions = []

        for param, value in filters.items():
            excluding_term = False
            param_parts = param.split("__")
            base_param = param_parts[0]  # only test against field without lookup
            negation_keyword = constants.NEGATION_KEYWORD
            if len(param_parts) > 1 and param_parts[1] == negation_keyword:
                excluding_term = True
                param = param.replace(f"__{negation_keyword}", "")  # haystack wouldn't understand our negation

            if self.view.serializer_class:
                if hasattr(self.view.serializer_class.Meta, "field_aliases"):
                    old_base = base_param
                    base_param = self.view.serializer_class.Meta.field_aliases.get(base_param, base_param)
                    param = param.replace(old_base, base_param)  # need to replace the alias

                fields = getattr(self.view.serializer_class.Meta, "fields", [])
                exclude = getattr(self.view.serializer_class.Meta, "exclude", [])
                search_fields = getattr(self.view.serializer_class.Meta, "search_fields", [])

                # Skip if the parameter is not listed in the serializer's `fields`
                # or if it's in the `exclude` list.
                if (
                    ((fields or search_fields) and base_param not in chain(fields, search_fields))
                    or base_param in exclude
                    or not value
                ):
                    continue

            param_queries = []
            if len(param_parts) > 1 and param_parts[-1] in ("in", "range"):
                # `in` and `range` filters expect a list of values
                param_queries.append(self.view.query_object((param, list(self.tokenize(value, self.view.lookup_sep)))))
            else:
                for token in self.tokenize(value, self.view.lookup_sep):
                    param_queries.append(self.view.query_object((param, token)))

            param_queries = [pq for pq in param_queries if pq]
            if param_queries:
                term = reduce(self.get_same_param_operator(param), param_queries)
                if excluding_term:
                    applicable_exclusions.append(term)
                else:
                    applicable_filters.append(term)

        applicable_filters = (
            reduce(self.default_operator, (x for x in applicable_filters if x))
            if applicable_filters
            else self.view.query_object()
        )
        applicable_exclusions = (
            reduce(self.default_operator, (x for x in applicable_exclusions if x))
            if applicable_exclusions
            else self.view.query_object()
        )

        return applicable_filters, applicable_exclusions


class FacetQueryBuilder(BaseQueryBuilder):
    """
    Query builder for field faceting. Builds field_facets from serializer Meta
    and query params (option1:value1,option2:value2).
    """

    def build_query(self, **filters):
        facet_serializer_cls = self.view.get_facet_serializer_class()
        if self.view.lookup_sep == ":":
            raise AttributeError(
                f"{self.view.__class__.__name__}.lookup_sep cannot be ':' (conflicts with facet query parser)."
            )

        fields = facet_serializer_cls.Meta.fields
        exclude = getattr(facet_serializer_cls.Meta, "exclude", ())
        meta_options = getattr(facet_serializer_cls.Meta, "field_options", {})
        field_options = {
            f: dict(meta_options.get(f, {}))
            for f in fields
            if f not in exclude
        }

        for field, options in filters.items():
            if field not in fields or field in exclude:
                continue
            opts_list = [options] if isinstance(options, str) else list(options)
            field_options[field] = merge_dict(
                field_options.get(field, {}),
                self._parse_field_options(*opts_list),
            )

        return {"field_facets": field_options}

    def _parse_field_options(self, *options):
        """Parse key:value pairs from query string (e.g. limit:10)."""
        out = {}
        for option in options:
            if not isinstance(option, str):
                continue
            for token in option.split(self.view.lookup_sep):
                token = token.strip()
                if ":" not in token:
                    warnings.warn(
                        f"Facet option '{token}' ignored; use 'key:value'.",
                        stacklevel=2,
                    )
                    continue
                key, value = token.split(":", 1)
                out[key.strip()] = value.strip()
        return out
