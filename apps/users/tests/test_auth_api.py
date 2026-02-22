"""API tests for auth (token login/logout) and user profile."""

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.users.tests.factories import UserFactory


class TokenAuthAPITestCase(APITestCase):
    def setUp(self):
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
