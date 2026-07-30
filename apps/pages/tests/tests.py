from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.pages.models import Page
from apps.pages.tests.factories import PageFactory
from apps.users.tests.factories import UserFactory

LEGACY_ABOUT_SLUGS = {"accessibility", "historical-context", "about-models-of-authority"}


class PagesAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.pages = PageFactory.create_batch(3)
        self.draft_page = PageFactory(status=Page.Status.DRAFT)

    def test_pages_list_api_only_returns_published(self):
        response = self.client.get("/api/v1/pages/")
        assert response.status_code == status.HTTP_200_OK
        slugs = {item["slug"] for item in response.data}
        assert slugs == {p.slug for p in self.pages} | LEGACY_ABOUT_SLUGS, response.data
        assert self.draft_page.slug not in slugs

    def test_legacy_about_pages_seeded(self):
        response = self.client.get("/api/v1/pages/")
        slugs = {item["slug"] for item in response.data}
        assert LEGACY_ABOUT_SLUGS <= slugs, response.data

    def test_page_detail_api(self):
        page = self.pages[0]
        response = self.client.get(f"/api/v1/pages/{page.slug}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == page.slug
        assert response.data["title"] == page.title
        assert response.data["content"] == page.content

    def test_draft_page_not_visible_publicly(self):
        response = self.client.get(f"/api/v1/pages/{self.draft_page.slug}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class PagesManagementAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_authenticate(self.superuser)

    def test_create_page(self):
        payload = {
            "slug": "project-team",
            "title": {"en": "Project team", "fr": "Équipe du projet"},
            "content": {"en": "<p>Hello</p>", "fr": "<p>Bonjour</p>"},
            "status": Page.Status.DRAFT,
        }
        response = self.client.post("/api/v1/management/pages/", payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Page.objects.filter(slug="project-team").exists()

    def test_cannot_create_page_with_duplicate_slug(self):
        # "accessibility" already exists — seeded by the legacy-about-pages
        # data migration (apps/pages/migrations/0002_seed_legacy_about_pages.py).
        payload = {
            "slug": "accessibility",
            "title": {"en": "Accessibility", "fr": "Accessibilité"},
            "content": {"en": "<p>Hi</p>", "fr": "<p>Salut</p>"},
        }
        response = self.client.post("/api/v1/management/pages/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_anonymous_cannot_write(self):
        self.client.force_authenticate(None)
        response = self.client.post(
            "/api/v1/management/pages/", {"slug": "x", "title": {}, "content": {}}, format="json"
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
