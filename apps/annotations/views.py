from django_filters import rest_framework as filters
from rest_framework import viewsets

from .models import Graph
from .serializers import GraphSerializer


class GraphViewSet(viewsets.ModelViewSet):
    queryset = Graph.objects.all()
    serializer_class = GraphSerializer
    pagination_class = None
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image", 'annotation_type']
