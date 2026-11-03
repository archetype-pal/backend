"""Each role rule is one predicate; the table below is the whole of who may do what."""

from django.contrib.auth.models import AnonymousUser
import pytest

from apps.common.permissions import can_annotate, can_annotate_editorially, can_manage, can_read_drafts
from apps.users.tests.factories import SuperuserFactory, UserFactory

pytestmark = pytest.mark.django_db

PREDICATES = (can_annotate, can_annotate_editorially, can_read_drafts, can_manage)


@pytest.mark.parametrize(
    ("make_user", "expected"),
    [
        (AnonymousUser, (False, False, False, False)),
        (UserFactory, (True, False, False, False)),
        (lambda: UserFactory(is_staff=True), (True, False, True, False)),
        (lambda: SuperuserFactory(is_staff=False), (True, True, True, True)),
        (SuperuserFactory, (True, True, True, True)),
    ],
    ids=["anonymous", "reader", "staff", "superuser-not-staff", "superuser"],
)
def test_who_may_do_what(make_user, expected):
    user = make_user()

    assert tuple(predicate(user) for predicate in PREDICATES) == expected
