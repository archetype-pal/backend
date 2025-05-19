from django import forms
from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html

from apps.symbols_structure.models import Position

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
from .widgets import ImagePickerWidget


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
    list_display = ["id", "get_catalogue_numbers", "date"]
    search_fields = [
        "date__name",
    ]
    inlines = [HistoricalItemDescriptionInline, CatalogueNumberInline]

    @admin.display(description=CatalogueNumber._meta.verbose_name_plural)
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
                ]
            },
        ),
        ("Additional Information", {"fields": ["language", "hair_type"]}),
    ]


class CurrentItemAdmin(admin.ModelAdmin):
    list_display = ["id", "repository", "shelfmark", "number_of_parts"]
    search_fields = ["repository__name", "shelfmark"]
    list_filter = ["repository"]


if settings.ENABLE_MODEL_IN_ADMIN_CURRENT_ITEM:
    admin.site.register(CurrentItem, CurrentItemAdmin)


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
    class ItemImageForm(forms.ModelForm):
        image = forms.CharField(widget=ImagePickerWidget)

        class Meta:
            model = ItemImage
            fields = "__all__"

    list_display = ["id", "item_part", "locus", "thumbnail_preview"]
    form = ItemImageForm

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

if settings.MOVE_POSITION_TO_OBJECTS:

    class PositionProxy(Position):
        class Meta:
            proxy = True
            app_label = "manuscripts"
            verbose_name = "Ogham Position"
            verbose_name_plural = "Ogham Positions"

    class PositionProxyAdmin(admin.ModelAdmin):
        list_display = ["name"]

    admin.site.register(PositionProxy, PositionProxyAdmin)
