"""API tests for auth (token login/logout) and user profile."""

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

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

    def test_token_logout_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/v1/auth/token/logout")
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))

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


class UserManagementAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_authenticate(self.superuser)

    def test_user_management_pagination_and_search(self):
        UserFactory(username="unique_user_alpha", email="alpha@example.com", is_staff=True)
        UserFactory(username="unique_user_beta", email="beta@example.com", is_staff=False)

        res = self.client.get("/api/v1/auth/management/users/?limit=1")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertGreaterEqual(res.data["count"], 2)

        res_search = self.client.get("/api/v1/auth/management/users/?search=unique_user_alpha")
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_search.data["results"]), 1)
        self.assertEqual(res_search.data["results"][0]["username"], "unique_user_alpha")

        res_staff = self.client.get("/api/v1/auth/management/users/?is_staff=true&search=unique_user")
        self.assertEqual(res_staff.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_staff.data["results"]), 1)
        self.assertEqual(res_staff.data["results"][0]["username"], "unique_user_alpha")

    def test_last_login_ordering_puts_never_logged_in_users_last(self):
        UserFactory(username="ordering_recent", last_login=timezone.now())
        UserFactory(username="ordering_never", last_login=None)

        for ordering in ("last_login", "-last_login"):
            res = self.client.get(f"/api/v1/auth/management/users/?search=ordering_&ordering={ordering}")
            self.assertEqual([row["username"] for row in res.data["results"]], ["ordering_recent", "ordering_never"])
