"""API tests for the superuser "impersonate another user" endpoint.

Token-swap equivalent of django-impersonate for this project's token-auth
architecture: a superuser POSTs to /management/users/{id}/impersonate/ and gets
back a short-lived credential that authenticates as the target user.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from apps.common.models import EditEvent
from apps.users.models import ImpersonationToken
from apps.users.tests.factories import SuperuserFactory, UserFactory


def _impersonate_url(user_id: int) -> str:
    return f"/api/v1/auth/management/users/{user_id}/impersonate/"


class ImpersonateAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = SuperuserFactory(username="admin")
        self.target = UserFactory(username="regular")

    def _impersonate(self, user_id: int):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.post(_impersonate_url(user_id))
        self.client.force_authenticate(user=None)
        return response

    def test_non_superuser_is_forbidden(self):
        requester = UserFactory(username="plain")
        self.client.force_authenticate(user=requester)

        response = self.client.post(_impersonate_url(self.target.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(EditEvent.objects.exists())

    def test_staff_but_not_superuser_is_forbidden(self):
        self.client.force_authenticate(user=UserFactory(username="staffer", is_staff=True))

        response = self.client.post(_impersonate_url(self.target.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(EditEvent.objects.exists())

    def test_anonymous_is_unauthorized_or_forbidden(self):
        response = self.client.post(_impersonate_url(self.target.id))

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_returned_token_authenticates_as_the_target(self):
        response = self._impersonate(self.target.id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['auth_token']}")
        profile = self.client.get("/api/v1/auth/profile")

        self.assertEqual(profile.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.data["username"], "regular")
        self.assertEqual(profile.data["impersonated_by"], "admin")

    def test_impersonation_does_not_disclose_the_targets_own_token(self):
        own_token = Token.objects.create(user=self.target)

        response = self._impersonate(self.target.id)

        self.assertNotEqual(response.data["auth_token"], own_token.key)

    def test_expired_token_no_longer_authenticates(self):
        response = self._impersonate(self.target.id)
        ImpersonationToken.objects.update(expires=timezone.now() - timedelta(seconds=1))

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['auth_token']}")

        self.assertEqual(self.client.get("/api/v1/auth/profile").status_code, status.HTTP_401_UNAUTHORIZED)

    def test_impersonation_creates_audit_event(self):
        self._impersonate(self.target.id)

        event = EditEvent.objects.get()
        self.assertEqual(event.actor, self.superuser)
        self.assertEqual(event.action, EditEvent.Action.IMPERSONATED)
        self.assertEqual(event.target_type, "user")
        self.assertEqual(event.target_id, self.target.id)

    def test_cannot_impersonate_self(self):
        response = self._impersonate(self.superuser.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(EditEvent.objects.exists())

    def test_cannot_impersonate_staff_user(self):
        staff_user = UserFactory(username="staffer", is_staff=True)

        response = self._impersonate(staff_user.id)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(EditEvent.objects.exists())

    def test_cannot_impersonate_another_superuser(self):
        other_superuser = SuperuserFactory(username="admin2")

        response = self._impersonate(other_superuser.id)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(EditEvent.objects.exists())

    def test_cannot_impersonate_inactive_user(self):
        inactive = UserFactory(username="disabled", is_active=False)

        response = self._impersonate(inactive.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(EditEvent.objects.exists())
