"""Every management operation is superuser-only: anonymous callers get 401, signed-in non-superusers 403.

One contract test over the routed URL tree, so a new management endpoint is
covered the moment it is routed and no endpoint needs its own permission tests.
DRF checks permissions before looking the object up, so a placeholder id is enough.
"""

import pytest

from apps.common.tests.routes import routed_operations

MANAGEMENT_OPERATIONS = sorted(op for op in routed_operations("1") if "management/" in op[0])


def test_the_management_surface_is_not_empty():
    assert len(MANAGEMENT_OPERATIONS) > 50


@pytest.mark.django_db
def test_anonymous_callers_are_rejected_from_every_management_operation(api_client):
    leaks = [
        (method.upper(), path)
        for path, method in MANAGEMENT_OPERATIONS
        if getattr(api_client, method)(path).status_code != 401
    ]
    assert not leaks, "Management operations reachable anonymously:\n" + "\n".join(f"{m} {p}" for m, p in leaks)


@pytest.mark.django_db
def test_non_superusers_are_rejected_from_every_management_operation(authenticated_client):
    leaks = [
        (method.upper(), path)
        for path, method in MANAGEMENT_OPERATIONS
        if getattr(authenticated_client, method)(path).status_code != 403
    ]
    assert not leaks, "Management operations open to non-superusers:\n" + "\n".join(f"{m} {p}" for m, p in leaks)
