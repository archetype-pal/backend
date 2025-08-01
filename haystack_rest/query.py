from itertools import chain
import operator
import warnings

from dateutil import parser
from functools import reduce

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


class BoostQueryBuilder(BaseQueryBuilder):
    """
    Query builder class for adding boost to queries.
    """

    def build_query(self, **filters):
        applicable_filters = None
        query_param = getattr(self.backend, "query_param", None)

        value = filters.pop(query_param, None)
        if value:
            try:
                term, val = chain.from_iterable(zip(self.tokenize(value, self.view.lookup_sep)))
            except ValueError:
                raise ValueError(f"Cannot convert the '{query_param}' query parameter to a valid boost filter.")
            else:
                try:
                    applicable_filters = {"term": term, "boost": float(val)}
                except ValueError:
                    raise ValueError(
                        "Cannot convert boost to float value. Make sure to provide a numerical boost value."
                    )

        return applicable_filters


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
            negation_keyword = constants.DRF_HAYSTACK_NEGATION_KEYWORD
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
            if len(param_queries) > 0:
                term = reduce(self.get_same_param_operator(param), param_queries)
                if excluding_term:
                    applicable_exclusions.append(term)
                else:
                    applicable_filters.append(term)

        applicable_filters = (
            reduce(self.default_operator, filter(lambda x: x, applicable_filters))
            if applicable_filters
            else self.view.query_object()
        )

        applicable_exclusions = (
            reduce(self.default_operator, filter(lambda x: x, applicable_exclusions))
            if applicable_exclusions
            else self.view.query_object()
        )

        return applicable_filters, applicable_exclusions


class FacetQueryBuilder(BaseQueryBuilder):
    """
    Query builder class suitable for constructing faceted queries.
    """

    def build_query(self, **filters):
        """
        Creates a dict of dictionaries suitable for passing to the  SearchQuerySet `facet`,
        `date_facet` or `query_facet` method. All key word arguments should be wrapped in a list.
        """
        field_facets = {}
        date_facets = {}
        query_facets = {}
        facet_serializer_cls = self.view.get_facet_serializer_class()

        if self.view.lookup_sep == ":":
            raise AttributeError(
                f"The {self.view.__class__.__name__}.lookup_sep attribute conflicts with the HaystackFacetFilter "
                "query parameter parser. Please choose another `lookup_sep` attribute "
                f"for {self.view.__class__.__name__}."
            )

        fields = facet_serializer_cls.Meta.fields
        exclude = facet_serializer_cls.Meta.exclude
        field_options = facet_serializer_cls.Meta.field_options

        for field, options in filters.items():
            if field not in fields or field in exclude:
                continue
            field_options = merge_dict(field_options, {field: self.parse_field_options(self.view.lookup_sep, *options)})

        valid_gap = ("year", "month", "day", "hour", "minute", "second")
        for field, options in field_options.items():
            if any(k in options for k in ("start_date", "end_date", "gap_by", "gap_amount")):
                if not all(k in options for k in ("start_date", "end_date", "gap_by")):
                    raise ValueError("Date faceting requires at least 'start_date', 'end_date' and 'gap_by' to be set.")
                if options["gap_by"] not in valid_gap:
                    raise ValueError(f"The 'gap_by' parameter must be one of {', '.join(valid_gap)}.")
                options.setdefault("gap_amount", 1)
                date_facets[field] = field_options[field]
            else:
                field_facets[field] = field_options[field]

        return {"date_facets": date_facets, "field_facets": field_facets, "query_facets": query_facets}

    def parse_field_options(self, *options):
        """
        Parse the field options query string and return it as a dictionary.
        """
        defaults = {}
        for option in options:
            if isinstance(option, str):
                tokens = [token.strip() for token in option.split(self.view.lookup_sep)]
                for token in tokens:
                    if len(token.split(":")) != 2:
                        warnings.warn(
                            f"The {token} token is not properly formatted. Tokens need to be formatted as 'token:value' pairs.", stacklevel=2
                        )
                        continue
                    param, value = token.split(":", 1)
                    if param in ("start_date", "end_date", "gap_amount"):
                        if param in ("start_date", "end_date"):
                            value = parser.parse(value)
                        if param == "gap_amount":
                            value = int(value)
                    defaults[param] = value
        return defaults
