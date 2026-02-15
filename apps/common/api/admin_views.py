from rest_framework import viewsets

from apps.common.api.permissions import IsAdminUser
from apps.common.models import Date

from .admin_serializers import DateAdminSerializer


class DateAdminViewSet(viewsets.ModelViewSet):
    queryset = Date.objects.all()
    serializer_class = DateAdminSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None
