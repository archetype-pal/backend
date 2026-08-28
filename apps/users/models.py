from django.conf import settings
from django.db import models


class ImpersonationToken(models.Model):
    """A short-lived credential that authenticates as ``user`` on behalf of ``impersonated_by``.

    Separate from ``authtoken.Token``, which is one row per user: handing over
    the target's own token gives away a permanent credential that cannot be
    revoked without signing the target out of their own session.
    """

    key = models.CharField(max_length=40, primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="impersonation_tokens")
    impersonated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    expires = models.DateTimeField()
