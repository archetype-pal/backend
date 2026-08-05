"""API tests for the superuser "impersonate another user" endpoint.

Token-swap equivalent of django-impersonate for this project's token-auth
architecture: a superuser POSTs to /management/users/{id}/impersonate/ and
gets back the target user's own auth token to swap into the frontend client.
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from apps.common.models import EditEvent
from apps.users.tests.factories import SuperuserFactory, UserFactory

User = get_user_model()


def _impersonate_url(user_id: int) -> str:
    return f"/api/v1/auth/management/users/{user_id}/impersonate/"


class ImpersonateAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = SuperuserFactory(username="admin")
        self.target = UserFactory(username="regular")

    def test_non_superuser_is_forbidden(self):
        requester = UserFactory(username="plain")
        self.client.force_authenticate(user=requester)

        response = self.client.post(_impersonate_url(self.target.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(EditEvent.objects.exists())

    def test_anonymous_is_unauthorized_or_forbidden(self):
        response = self.client.post(_impersonate_url(self.target.id))

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_superuser_impersonating_regular_user_returns_token(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.post(_impersonate_url(self.target.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_token = Token.objects.get(user=self.target)
        self.assertEqual(response.data["auth_token"], expected_token.key)

    def test_impersonation_reuses_existing_token(self):
        self.client.force_authenticate(user=self.superuser)
        existing_token = Token.objects.create(user=self.target)

        response = self.client.post(_impersonate_url(self.target.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["auth_token"], existing_token.key)
        self.assertEqual(Token.objects.filter(user=self.target).count(), 1)

    def test_impersonation_creates_audit_event(self):
        self.client.force_authenticate(user=self.superuser)

        self.client.post(_impersonate_url(self.target.id))

        event = EditEvent.objects.get()
        self.assertEqual(event.actor, self.superuser)
        self.assertEqual(event.action, EditEvent.Action.IMPERSONATED)
        self.assertEqual(event.target_type, "user")
        self.assertEqual(event.target_id, self.target.id)

    def test_cannot_impersonate_self(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.post(_impersonate_url(self.superuser.id))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(EditEvent.objects.exists())

    def test_cannot_impersonate_staff_user(self):
        self.client.force_authenticate(user=self.superuser)
        staff_user = UserFactory(username="staffer", is_staff=True)

        response = self.client.post(_impersonate_url(staff_user.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(EditEvent.objects.exists())

    def test_cannot_impersonate_another_superuser(self):
        self.client.force_authenticate(user=self.superuser)
        other_superuser = SuperuserFactory(username="admin2")

        response = self.client.post(_impersonate_url(other_superuser.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(EditEvent.objects.exists())
