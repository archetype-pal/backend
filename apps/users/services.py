from django.contrib.auth import get_user_model
from django.db.models import Count, Q

User = get_user_model()


def get_user_counts() -> dict[str, int]:
    """Totals over every user, ignoring search and filters."""
    counts: dict[str, int] = User.objects.aggregate(
        total=Count("pk"),
        superusers=Count("pk", filter=Q(is_superuser=True)),
        staff=Count("pk", filter=Q(is_staff=True)),
        active=Count("pk", filter=Q(is_active=True)),
    )
    counts["inactive"] = counts["total"] - counts["active"]
    return counts
