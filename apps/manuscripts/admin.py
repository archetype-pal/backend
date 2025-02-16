from django.contrib import admin
from django.utils.html import format_html

from .models import (
    BibliographicSource,
    CatalogueNumber,
    CurrentItem,
    HistoricalItem,
    HistoricalItemDescription,
    ImageText,
    ItemFormat,
    ItemImage,
    ItemPart,
    Repository,
)


class HistoricalItemDescriptionInline(admin.TabularInline):
    model = HistoricalItemDescription
    extra = 1
    fields = ["source", "content"]


class CatalogueNumberInline(admin.TabularInline):
    model = CatalogueNumber
    extra = 0
    fields = ["number", "catalogue", "url"]


@admin.register(HistoricalItem)
class HistoricalItemAdmin(admin.ModelAdmin):
    list_display = ["id", "get_catalogue_numbers_display", "date", "issuer", "named_beneficiary"]
    search_fields = ["date", "issuer", "named_beneficiary"]
    inlines = [HistoricalItemDescriptionInline, CatalogueNumberInline]

    @admin.display(description="Catalogue Numbers")
    def get_catalogue_numbers(self, obj):
        return obj.get_catalogue_numbers_display()

    readonly_fields = ["get_catalogue_numbers"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "type",
                    "date",
                    "get_catalogue_numbers",
                    "format",
                    "issuer",
                    "named_beneficiary",
                ]
            },
        ),
        ("Additional Information", {"fields": ["language", "vernacular", "neumed", "hair_type"]}),
    ]


@admin.register(CurrentItem)
class CurrentItemAdmin(admin.ModelAdmin):
    list_display = ["id", "repository", "shelfmark", "number_of_parts"]
    search_fields = ["repository__name", "shelfmark"]
    list_filter = ["repository"]


@admin.register(ItemPart)
class ItemPartAdmin(admin.ModelAdmin):
    list_display = ["id", "historical_item", "current_item", "historical_item__type"]
    search_fields = ["historical_item__issuer", "historical_item__named_beneficiary"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "historical_item",
                    "custom_label",
                ]
            },
        ),
        ("This part is currently found in ...", {"fields": ["current_item", "current_item_locus"]}),
    ]


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ["name", "label", "place", "url"]
    search_fields = ["name", "label"]


@admin.register(ItemImage)
class ItemImageAdmin(admin.ModelAdmin):
    list_display = ["id", "item_part", "locus", "thumbnail_preview"]

    def thumbnail_preview(self, obj):
        if obj.image:
            return format_html('<a href="{}"> <img src="{}"/> </a>', obj.image.url, obj.image.iiif.thumbnail)
        else:
            return "No Image"

    thumbnail_preview.short_description = "Thumbnail"


@admin.register(BibliographicSource)
class BibliographicSourceAdmin(admin.ModelAdmin):
    list_display = ["name", "label"]
    search_fields = ["name", "label"]


admin.site.register(ItemFormat)
admin.site.register(CatalogueNumber)
admin.site.register(ImageText)
