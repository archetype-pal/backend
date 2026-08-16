"""API tests for auth (token login/logout) and user profile."""

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from apps.users.models import ImpersonationToken
from apps.users.tests.factories import UserFactory


class TokenAuthAPITestCase(APITestCase):
    def setUp(self):
        cache.clear()  # throttle history is process-local and TestCase never resets it
        self.client = APIClient()
        self.user = UserFactory(username="testuser", email="test@example.com")
        self.user.set_password("testpass123")
        self.user.save()

    def test_token_login_success(self):
        response = self.client.post(
            "/api/v1/auth/token/login",
            {"username": "testuser", "password": "testpass123"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("auth_token", response.data)
        self.assertTrue(len(response.data["auth_token"]) > 0)

    def test_token_login_invalid_credentials(self):
        response = self.client.post(
            "/api/v1/auth/token/login",
            {"username": "testuser", "password": "wrongpassword"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def _login(self, **extra):
        return self.client.post(
            "/api/v1/auth/token/login",
            {"username": "testuser", "password": "wrongpassword"},
            format="json",
            **extra,
        )

    def test_login_is_throttled(self):
        for _ in range(10):
            self.assertNotEqual(self._login().status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(self._login().status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_login_is_throttled_for_authenticated_requests(self):
        self.client.force_authenticate(user=self.user)
        for _ in range(10):
            self.assertNotEqual(self._login().status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(self._login().status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 2})
    def test_login_bucket_keys_on_the_num_proxies_hop(self):
        for i in range(10):
            response = self._login(HTTP_X_FORWARDED_FOR=f"{i}.{i}.{i}.{i}, 9.9.9.9, 10.0.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        # Same second-from-last hop → same bucket, whatever prefix the client invents.
        response = self._login(HTTP_X_FORWARDED_FOR="1.1.1.1, 9.9.9.9, 10.0.0.1")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        # Different second-from-last hop → different bucket (fails if NUM_PROXIES were 1).
        response = self._login(HTTP_X_FORWARDED_FOR="1.1.1.1, 8.8.8.8, 10.0.0.1")
        self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_token_logout_revokes_only_the_presented_credential(self):
        other = UserFactory(username="bystander")
        other_token = Token.objects.create(user=other)
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = self.client.post("/api/v1/auth/token/logout")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())
        self.assertTrue(Token.objects.filter(pk=other_token.pk).exists())

    def test_logout_while_impersonating_leaves_the_targets_own_token(self):
        impersonation = ImpersonationToken.objects.create(
            key="imp",
            user=self.user,
            impersonated_by=UserFactory(username="admin"),
            expires=timezone.now() + timedelta(hours=1),
        )
        own_token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {impersonation.key}")

        response = self.client.post("/api/v1/auth/token/logout")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(Token.objects.filter(pk=own_token.pk).exists())
        self.assertFalse(ImpersonationToken.objects.exists())

    def test_profile_requires_auth(self):
        response = self.client.get("/api/v1/auth/profile")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profile_returns_current_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/v1/auth/profile")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "testuser")
        self.assertEqual(response.data["email"], "test@example.com")
        self.assertIn("is_superuser", response.data)
