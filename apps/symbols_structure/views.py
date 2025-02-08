from rest_framework.generics import ListAPIView

from .models import Allograph, Position
from .serializers import AllographSerializer, PositionSerializer


class AllographListView(ListAPIView):
    queryset = Allograph.objects.all()
    serializer_class = AllographSerializer
    pagination_class = None


class PositionListView(ListAPIView):
    queryset = Position.objects.all()
    serializer_class = PositionSerializer
    pagination_class = None
