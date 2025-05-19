from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
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
    list_display = ["id", "name", "get_catalogue_numbers", "date"]
    search_fields = [
        "date__name",
    ]
    inlines = [HistoricalItemDescriptionInline, CatalogueNumberInline]

    @admin.display(description=CatalogueNumber._meta.verbose_name_plural)
    def get_catalogue_numbers(self, obj):
        return obj.get_catalogue_numbers_display()

    readonly_fields = ["get_catalogue_numbers"]

    def get_fieldsets(self, request, obj=None):
        model_path = f"{self.model._meta.app_label}.{self.model.__name__}"
        hidden_fields = getattr(settings, "ADMIN_HIDDEN_FIELDS", {}).get(model_path, [])

        # Filter out hidden fields from the main fieldset
        main_fields = [
            field
            for field in [
                "name",
                "type",
                "date",
                "get_catalogue_numbers",
                "format",
                "current_location_latitude",
                "current_location_longitude",
                "original_location_longitude",
                "original_location_latitude",
            ]
            if field not in hidden_fields
        ]

        return [
            (
                None,
                {"fields": main_fields},
            ),
            ("Additional Information", {"fields": ["language", "hair_type"]}),
        ]


class CurrentItemAdmin(admin.ModelAdmin):
    list_display = ["id", "repository", "shelfmark", "number_of_parts"]
    search_fields = ["repository__name", "shelfmark"]
    list_filter = ["repository"]


if settings.ENABLE_MODEL_IN_ADMIN_CURRENT_ITEM:
    admin.site.register(CurrentItem, CurrentItemAdmin)


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


if settings.ENABLE_MODEL_IN_ADMIN_ITEM_PART:
    admin.site.register(ItemPart, ItemPartAdmin)


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ["name", "label", "place", "url"]
    search_fields = ["name", "label"]


@admin.register(ItemImage)
class ItemImageAdmin(admin.ModelAdmin):
    class ItemImageForm(forms.ModelForm):
        image = forms.CharField(widget=ImagePickerWidget)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            app_label, model = settings.ITEM_IMAGE_DEFAULT_MODEL.split(".")
            content_type = ContentType.objects.get(model=model.lower(), app_label=app_label.lower())
            self.fields["object_id"] = forms.ModelChoiceField(
                queryset=content_type.model_class().objects.all(),
                label=content_type.model_class()._meta.verbose_name,
                to_field_name="id",
            )

        def clean_object_id(self):
            value = self.cleaned_data["object_id"]
            if hasattr(value, "id"):
                return value.id
            return value

        class Meta:
            model = ItemImage
            exclude = ["content_type"]
            fields = ["image", "locus", "object_id", "copyright"]

    list_display = ["id", "locus", "thumbnail_preview", "get_related_object"]

    def get_related_object(self, obj):
        if obj.content_type and obj.object_id:
            return obj.content_object
        return None

    get_related_object.short_description = "Related Item"  # Column header in admin

    form = ItemImageForm

    def save_model(self, request, obj, form, change):
        if not change:  # Only for new objects
            app_label, model = settings.ITEM_IMAGE_DEFAULT_MODEL.split(".")
            content_type = ContentType.objects.get(model=model.lower(), app_label=app_label.lower())
            obj.content_type = content_type
        super().save_model(request, obj, form, change)

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
