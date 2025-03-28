from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.viewsets import ViewSetMixin

from haystack_rest.generics import HaystackGenericAPIView


class HaystackViewSet(RetrieveModelMixin, ListModelMixin, ViewSetMixin, HaystackGenericAPIView):
    """
    The HaystackViewSet class provides the default ``list()`` and
    ``retrieve()`` actions with a haystack index as it's data source.
    """

    pass
