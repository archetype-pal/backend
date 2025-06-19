from django import forms
from django.contrib import admin

from apps.manuscripts.models import ItemImage

from .models import Hand, Scribe, Script


@admin.register(Scribe)
class ScribeAdmin(admin.ModelAdmin):
    list_display = ["name", "period", "scriptorium"]
    search_fields = ["name", "period", "scriptorium"]


class HandAdminForm(forms.ModelForm):
    class Meta:
        model = Hand
        fields = ["scribe", "item_part", "script", "name", "date", "place", "description", "item_part_images"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter item_part_images based on the selected item_part
        if self.instance and self.instance.item_part_id:
            self.fields["item_part_images"].queryset = ItemImage.objects.filter(item_part=self.instance.item_part)
        else:
            self.fields["item_part_images"].queryset = ItemImage.objects.all()


@admin.register(Hand)
class HandAdmin(admin.ModelAdmin):
    form = HandAdminForm
    list_display = ["id", "item_part", "name", "scribe", "script", "date", "place"]
    filter_horizontal = ["item_part_images"]
    fieldsets = (
        ("Main information", {"fields": ("item_part", "scribe")}),
        ("Other info", {"fields": ("name", "script", "date", "place")}),
        ("Images", {"fields": ("item_part_images",)}),
    )

    class Media:
        js = ("admin/js/hand_admin.js",)


admin.site.register(Script)
