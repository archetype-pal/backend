import nested_admin
from django.contrib import admin

from apps.symbols_structure.models import Allograph, AllographComponent, Character, Component, Feature, Position


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("name", "type")


class AllographComponentFeatureInline(nested_admin.nested.NestedStackedInline):
    model = AllographComponent.features.through
    extra = 1
    fields = ["allograph_component", "feature", "set_by_default"]


class AllographComponentInline(nested_admin.nested.NestedTabularInline):
    model = AllographComponent
    inlines = [AllographComponentFeatureInline]
    extra = 1
    fields = ["component"]


@admin.register(Allograph)
class AllographAdmin(nested_admin.nested.NestedModelAdmin):
    list_display = ["name", "character"]
    inlines = [AllographComponentInline]

    fieldsets = ((None, {"fields": ("name", "character")}),)


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ["name"]
    fields = ["name", "features"]
    filter_horizontal = ["features"]


admin.site.register(Feature)
admin.site.register(Position)
