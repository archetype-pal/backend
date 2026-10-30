from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.common.models import AppSettings, Date, Place, SiteLabel
from apps.common.services.site_features import SITE_FEATURES_KEY_PREFIX, flatten_settings


def validated_data(serializer_class: type[serializers.Serializer], data: Any, **context: Any) -> Any:
    """Run `serializer_class` over `data`, raising DRF's 400 on invalid input; returns `validated_data`."""
    serializer = serializer_class(data=data, context=context)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class UserSummarySerializer(serializers.ModelSerializer):
    """How a user is shown inside another resource (an author, an owner, a reviewer)."""

    class Meta:
        model = get_user_model()
        fields = ["id", "username", "first_name", "last_name"]


class DateManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Date
        fields = ["id", "date", "min_weight", "max_weight"]


class PlaceManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = ["id", "name"]

    def validate_name(self, value: str) -> str:
        # DRF doesn't enforce the Lower("name") constraint; without this it's a 500.
        name = value.strip()
        duplicates = Place.objects.filter(name__iexact=name)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("A place with this name already exists.")
        return name


# --- site labels -------------------------------------------------------------

# Labels holding a link target rather than copy. The frontend renders them as
# `href`s, so only site-relative paths and http(s) URLs are accepted — never a
# `javascript:` or protocol-relative (`//host`) value. Empty means "no link".
SITE_LABEL_URL_KEYS = frozenset({SiteLabel.Key.HOME_ABOUT_URL, SiteLabel.Key.HOME_CONTEXT_URL})


def is_safe_link(value: str) -> bool:
    value = value.strip()
    if not value:
        return True
    if value.startswith("/"):
        # Browsers read a backslash as a slash here, so "/\\evil.example" is as
        # protocol-relative as "//evil.example".
        return value[1:2] not in ("/", "\\")
    return value.lower().startswith(("http://", "https://"))


class StrictCharField(serializers.CharField):
    """A string and nothing else — `CharField` would silently accept and stringify a number."""

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class SiteLabelsWriteSerializer(serializers.Serializer):
    """`{"labels": {key: {lang: text}}}` — only the keys present are upserted."""

    labels = serializers.DictField(
        child=serializers.DictField(child=StrictCharField(allow_blank=True), allow_empty=False),
        allow_empty=False,
    )

    def validate_labels(self, labels: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        unknown = set(labels) - set(SiteLabel.Key.values)
        if unknown:
            raise serializers.ValidationError(f"Unknown key(s): {sorted(unknown)}")
        unsafe = [
            key
            for key, value in labels.items()
            if key in SITE_LABEL_URL_KEYS and not all(map(is_safe_link, value.values()))
        ]
        if unsafe:
            raise serializers.ValidationError(f"Link(s) for key(s) {sorted(unsafe)} must be a /path or an http(s) URL.")
        return labels


# --- site features -----------------------------------------------------------


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data: Any) -> Any:
        # PUT is a destructive full replace, so an unknown key would be dropped
        # by DRF and then have its stored rows deleted behind a 200.
        if isinstance(data, dict) and (unknown := set(data) - set(self.fields)):
            raise serializers.ValidationError({key: "Unknown key." for key in unknown})
        return super().to_internal_value(data)


class SearchCategoryWriteSerializer(StrictSerializer):
    enabled = serializers.BooleanField()
    visibleColumns = serializers.ListField(child=serializers.CharField())
    visibleFacets = serializers.ListField(child=serializers.CharField())


HEX_COLOR_REGEX = r"^#[0-9a-fA-F]{6}$"


class ThemeWriteSerializer(StrictSerializer):
    primaryColor = serializers.RegexField(HEX_COLOR_REGEX)
    primaryForegroundColor = serializers.RegexField(HEX_COLOR_REGEX)
    accentColor = serializers.RegexField(HEX_COLOR_REGEX)
    titleBarBackgroundColor = serializers.RegexField(HEX_COLOR_REGEX)
    titleBarTextColor = serializers.RegexField(HEX_COLOR_REGEX)
    navBarBackgroundColor = serializers.RegexField(HEX_COLOR_REGEX)
    navBarTextColor = serializers.RegexField(HEX_COLOR_REGEX)


class BrandingWriteSerializer(StrictSerializer):
    # Either a manually-typed external URL or the path `BrandingLogoUploadView`
    # handed back (`default_storage.url(...)`, e.g. "/media/branding/x.png") —
    # `branding.logoUrl` is a plain string leaf either way. Blank means no logo.
    logoUrl = serializers.CharField(allow_blank=True)


MAX_LOGO_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB, matches the frontend's ImageUploadZone limit


def validate_logo_upload_size(file) -> None:
    if file.size > MAX_LOGO_UPLOAD_SIZE:
        raise serializers.ValidationError(f"Image must be {MAX_LOGO_UPLOAD_SIZE // (1024 * 1024)}MB or smaller.")


class BrandingLogoUploadSerializer(serializers.Serializer):
    logo = serializers.ImageField(validators=[validate_logo_upload_size])


class SiteFeaturesWriteSerializer(StrictSerializer):
    sections = serializers.DictField(child=serializers.BooleanField(), allow_empty=False)
    sectionOrder = serializers.ListField(child=serializers.CharField())
    features = serializers.DictField(child=serializers.BooleanField(), allow_empty=False)
    theme = ThemeWriteSerializer()
    branding = BrandingWriteSerializer()
    searchCategories = serializers.DictField(child=SearchCategoryWriteSerializer(), allow_empty=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        limit = AppSettings._meta.get_field("key").max_length - len(SITE_FEATURES_KEY_PREFIX)
        if any(len(dotted_key) > limit for dotted_key in flatten_settings(attrs)):
            raise serializers.ValidationError(f"Setting keys must be at most {limit} characters.")
        return attrs
