from django.contrib import admin
from rest_framework.authtoken.models import TokenProxy
from .models import Date

admin.site.unregister(TokenProxy)

admin.site.register(Date)
