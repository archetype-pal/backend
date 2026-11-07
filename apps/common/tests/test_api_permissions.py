"""Who may call what, swept over the routed URL tree so a route is covered the moment it exists.

- Every `management/` operation, read or write, is superuser-only.
- Every other unsafe operation is superuser-only too, unless `OTHER_WRITES` lists it
  with the tier it requires and why. A caller one tier below that tier is refused.

Superuser-only means anonymous callers get 401 and signed-in non-superusers 403.
Routes come from the URL conf, never from the permission class being checked, so a
forgotten permission class cannot also hide its route from this test. DRF checks
permissions before looking the object up, so a placeholder id is enough, except
where the check is ownership of a real row.
"""

from enum import StrEnum

import pytest

from apps.common.tests.routes import routed_operations
from apps.worksets.models import Workset
from apps.worksets.tests.factories import WorksetFactory

PLACEHOLDER = "1"
UNSAFE_METHODS = ("post", "put", "patch", "delete")


class Tier(StrEnum):
    ANONYMOUS = "anonymous"
    SIGNED_IN = "signed in"
    OWNER = "owner"


# Every unsafe operation a non-superuser may call. Adding a row opens a write
# to more callers than the superusers, so it is a reviewed security decision.
OTHER_WRITES: dict[tuple[str, str], tuple[Tier, str]] = {
    ("post", "/api/v1/auth/token/login"): (Tier.ANONYMOUS, "Signing in; throttled per address."),
    ("post", "/api/v1/media/publications/1/comments/"): (
        Tier.ANONYMOUS,
        "Public comments; throttled, and a guest's comment waits for moderation.",
    ),
    ("post", "/api/v1/auth/token/logout"): (Tier.SIGNED_IN, "Revokes the caller's own token."),
    ("post", "/api/v1/annotations/graphs/"): (
        Tier.SIGNED_IN,
        "The image viewer's annotation writes; editorial annotations stay superuser-only.",
    ),
    ("patch", "/api/v1/annotations/graphs/1/"): (Tier.SIGNED_IN, "As above."),
    ("delete", "/api/v1/annotations/graphs/1/"): (Tier.SIGNED_IN, "As above."),
    ("post", "/api/v1/manuscripts/image-texts/validate-tei/"): (
        Tier.SIGNED_IN,
        "A well-formedness check for the text editor; writes nothing.",
    ),
    ("post", "/api/v1/manuscripts/image-texts/format-tei/"): (
        Tier.SIGNED_IN,
        "A reformat for the text editor; writes nothing.",
    ),
    ("post", "/api/v1/vision/pages/1/suggest/"): (
        Tier.SIGNED_IN,
        "A researcher asks a model about a shape they drew; writes only a proposal, throttled and under the spend cap.",
    ),
    ("post", "/api/v1/vision/suggestions/1/reject/"): (
        Tier.SIGNED_IN,
        "Turns down the caller's own suggestion; another's is a 404.",
    ),
    ("post", "/api/v1/vision/graphs/1/explain/"): (
        Tier.SIGNED_IN,
        "Asks a model why an annotation is its allograph; changes no record, throttled and under the spend cap.",
    ),
    ("post", "/api/v1/agent/ask/"): (
        Tier.ANONYMOUS,
        "The public read-only agent (AI programme W3.1); its own throttle, and refused while inference is off.",
    ),
    ("post", "/api/v1/learn/sessions/"): (
        Tier.ANONYMOUS,
        "Starts a tutor lesson (AI programme W4.4); a picture of one's own only as LEARN_UPLOADS allows. Its own "
        "throttle and daily allowance, and refused while inference is off.",
    ),
    ("post", "/api/v1/learn/sessions/1/questions/"): (
        Tier.ANONYMOUS,
        "Asks a lesson a question; refused to anyone but its starter, known by account or by a digest of address.",
    ),
    ("post", "/api/v1/worksets/"): (Tier.SIGNED_IN, "Creates a workset owned by the caller."),
    ("put", "/api/v1/worksets/1/"): (Tier.OWNER, "Only a workset's owner changes it."),
    ("patch", "/api/v1/worksets/1/"): (Tier.OWNER, "As above."),
    ("delete", "/api/v1/worksets/1/"): (Tier.OWNER, "Only a workset's owner deletes it."),
}

OPERATIONS = routed_operations(PLACEHOLDER)
SUPERUSER_ONLY = sorted(
    (path, method)
    for path, method in OPERATIONS
    if "management/" in path or (method in UNSAFE_METHODS and (method, path) not in OTHER_WRITES)
)


def _someone_elses_public_workset(path):
    workset = WorksetFactory(visibility=Workset.Visibility.PUBLIC)
    return path.replace(f"/{PLACEHOLDER}/", f"/{workset.public_id}/")


# For each owner-tier path: a row the signed-in caller does not own, and the path to it.
SOMEONE_ELSES_ROW = {"/api/v1/worksets/1/": _someone_elses_public_workset}


def test_the_superuser_only_surface_is_not_empty():
    assert len(SUPERUSER_ONLY) > 50


def test_every_listed_write_is_routed():
    stale = [f"{method.upper()} {path}" for method, path in OTHER_WRITES if (path, method) not in OPERATIONS]
    assert not stale, "OTHER_WRITES lists operations no route serves:\n" + "\n".join(stale)


def test_every_owner_tier_write_has_a_row_to_try():
    owner_paths = {path for (_, path), (tier, _) in OTHER_WRITES.items() if tier is Tier.OWNER}
    assert owner_paths == set(SOMEONE_ELSES_ROW)


@pytest.mark.django_db
def test_anonymous_callers_are_rejected_from_every_superuser_only_operation(api_client):
    leaks = [
        (method.upper(), path)
        for path, method in SUPERUSER_ONLY
        if getattr(api_client, method)(path).status_code != 401
    ]
    assert not leaks, "Superuser-only operations reachable anonymously:\n" + "\n".join(f"{m} {p}" for m, p in leaks)


@pytest.mark.django_db
def test_non_superusers_are_rejected_from_every_superuser_only_operation(authenticated_client):
    leaks = [
        (method.upper(), path)
        for path, method in SUPERUSER_ONLY
        if getattr(authenticated_client, method)(path).status_code != 403
    ]
    assert not leaks, "Superuser-only operations open to non-superusers:\n" + "\n".join(f"{m} {p}" for m, p in leaks)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [operation for operation, (tier, _) in OTHER_WRITES.items() if tier is not Tier.ANONYMOUS],
)
def test_anonymous_callers_are_rejected_from_every_signed_in_write(api_client, method, path):
    assert getattr(api_client, method)(path).status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [operation for operation, (tier, _) in OTHER_WRITES.items() if tier is Tier.OWNER],
)
def test_signed_in_callers_are_refused_someone_elses_row(authenticated_client, method, path):
    # 404 rather than 403 is fine: the row stays unchanged either way.
    assert getattr(authenticated_client, method)(SOMEONE_ELSES_ROW[path](path)).status_code in (403, 404)
