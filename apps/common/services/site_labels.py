"""The customizable UI label translations, stored one `SiteLabel` row per key."""

from typing import Any

from django.db import transaction

from apps.common.models import SiteLabel


def upsert_site_labels(labels: dict[str, Any]) -> None:
    """Write every key in *labels*, all or none; keys absent from *labels* are left as they are."""
    with transaction.atomic():
        for key, value in labels.items():
            SiteLabel.objects.update_or_create(key=key, defaults={"value": value})
