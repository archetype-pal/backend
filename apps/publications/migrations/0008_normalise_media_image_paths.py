"""Strip a stray MEDIA_URL prefix from stored carousel and partner image names.

The backoffice used to persist what it held — `/media/carousel/x.jpg` or the
absolute media URL — so the ImageField's `.url` prefixed `/media/` a second
time. The serializer now normalises input; this brings existing rows in line.
"""

from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.db import migrations


def _media_relative_path(value: str) -> str | None:
    """Mirror of `apps.publications.serializers.media_relative_path`; None for a URL outside MEDIA_URL,
    which this one-way migration leaves as it found it rather than turn into a missing file."""
    media_prefix = urlsplit(settings.MEDIA_URL).path.strip("/")
    if value.startswith(("http://", "https://")):
        path = unquote(urlsplit(value).path).lstrip("/")
        if not media_prefix or not path.startswith(f"{media_prefix}/"):
            return None
        return path[len(media_prefix) + 1 :]
    value = unquote(value).lstrip("/")
    if media_prefix and value.startswith(f"{media_prefix}/"):
        value = value[len(media_prefix) + 1 :]
    return value


def normalise_paths(apps, schema_editor):
    for model_name, field in (("CarouselItem", "image"), ("Partner", "logo")):
        model = apps.get_model("publications", model_name)
        for row in model.objects.exclude(**{field: ""}).only("id", field):
            current = getattr(row, field).name
            fixed = _media_relative_path(current)
            if fixed and fixed != current:
                setattr(row, field, fixed)
                row.save(update_fields=[field])


class Migration(migrations.Migration):
    dependencies = [
        ("publications", "0007_comment_is_deleted"),
    ]

    operations = [
        migrations.RunPython(normalise_paths, migrations.RunPython.noop),
    ]
