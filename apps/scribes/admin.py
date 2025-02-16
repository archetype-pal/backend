from django.contrib import admin

from .models import Hand, Scribe, Script


@admin.register(Scribe)
class ScribeAdmin(admin.ModelAdmin):
    list_display = ["name", "period", "scriptorium"]
    search_fields = ["name", "period", "scriptorium"]


@admin.register(Hand)
class HandAdmin(admin.ModelAdmin):
    list_display = ["id", "item_part", "name", "scribe", "script", "date", "place"]
    filter_horizontal = ["item_part_images"]
    fieldsets = (
        ("Main information", {"fields": ("item_part", "scribe")}),
        ("Other info", {"fields": ("name", "script", "date", "place")}),
        ("Images", {"fields": ("item_part_images",)}),
    )


admin.site.register(Script)
