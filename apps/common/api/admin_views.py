from apps.common.api.base_admin_views import UnpaginatedAdminViewSet
from apps.common.models import Date

from .admin_serializers import DateAdminSerializer


class DateAdminViewSet(UnpaginatedAdminViewSet):
    queryset = Date.objects.all()
    serializer_class = DateAdminSerializer
