from django.contrib import admin
from rest_framework.authtoken.models import TokenProxy

from .models import Date

admin.site.unregister(TokenProxy)


@admin.register(Date)
class DateAdmin(admin.ModelAdmin):
    list_display = ("date", "min_weight", "max_weight")
    search_fields = ("date", "min_weight", "max_weight")
