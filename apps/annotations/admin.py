from django.contrib import admin

from .models import Graph


class GraphComponentInline(admin.TabularInline):
    model = Graph.components.through
    extra = 1
    fields = ["component", "features"]
    filter_horizontal = ["features"]


@admin.register(Graph)
class GraphAdmin(admin.ModelAdmin):
    list_display = ["id", "hand", "allograph"]
    inlines = [GraphComponentInline]
