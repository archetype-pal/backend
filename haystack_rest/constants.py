from django.conf import settings

# Query param keyword for negation, e.g. field__not=value
NEGATION_KEYWORD: str = getattr(settings, "HAYSTACK_REST_NEGATION_KEYWORD", "not")
