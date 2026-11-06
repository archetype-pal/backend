from rest_framework import status
from rest_framework.test import APITestCase

from apps.pages.models import MenuHeading, Page
from apps.pages.tests.factories import MenuHeadingFactory, PageFactory
from apps.users.tests.factories import SuperuserFactory

LEGACY_ABOUT_SLUGS = {"accessibility", "historical-context", "about-models-of-authority"}
QUICK_LINK_SLUGS = {"about-models-of-authority", "accessibility"}


class PagesAPITestCase(APITestCase):
    def setUp(self):
        self.pages = PageFactory.create_batch(3)
        self.draft_page = PageFactory(status=Page.Status.DRAFT)

    def test_only_published_pages_are_public(self):
        response = self.client.get("/api/v1/pages/")
        assert response.status_code == status.HTTP_200_OK
        slugs = {item["slug"] for item in response.data}
        assert {p.slug for p in self.pages} <= slugs, response.data
        assert self.draft_page.slug not in slugs
        assert self.client.get(f"/api/v1/pages/{self.draft_page.slug}/").status_code == status.HTTP_404_NOT_FOUND

    def test_seeded_about_pages_are_published_under_no_heading_with_their_quick_links(self):
        # 0002_seed_legacy_about_pages: the footer links an install ships with.
        response = self.client.get("/api/v1/pages/")
        legacy = {item["slug"]: item for item in response.data if item["slug"] in LEGACY_ABOUT_SLUGS}
        assert set(legacy) == LEGACY_ABOUT_SLUGS, response.data
        assert all(item["menu_heading"] is None for item in legacy.values())
        assert {slug for slug, item in legacy.items() if item["include_in_quick_link"]} == QUICK_LINK_SLUGS

    def test_page_detail_api(self):
        page = self.pages[0]
        response = self.client.get(f"/api/v1/pages/{page.slug}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == page.slug
        assert response.data["title"] == page.title
        assert response.data["content"] == page.content

    def test_page_exposes_its_menu_heading_slug(self):
        heading = MenuHeadingFactory(slug="help")
        page = PageFactory(menu_heading=heading)
        response = self.client.get(f"/api/v1/pages/{page.slug}/")
        assert response.data["menu_heading"] == "help"
        listed = {item["slug"]: item for item in self.client.get("/api/v1/pages/").data}
        assert listed[page.slug]["menu_heading"] == "help"

    def test_menu_headings_list_is_public(self):
        MenuHeadingFactory(slug="help")
        response = self.client.get("/api/v1/menu-headings/")
        assert response.status_code == status.HTTP_200_OK
        assert [item["slug"] for item in response.data] == ["help"]


class PagesManagementAPITestCase(APITestCase):
    def setUp(self):
        self.superuser = SuperuserFactory()
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

    def test_cannot_create_page_with_reserved_slug(self):
        # Next resolves /backoffice/pages/new to the editor route, so a page
        # slugged "new" would be created and then be unreachable for editing.
        payload = {"slug": "new", "title": {"en": "New"}, "content": {"en": "<p>Hi</p>"}}
        response = self.client.post("/api/v1/management/pages/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert not Page.objects.filter(slug="new").exists()

    def test_assign_page_to_menu_heading(self):
        MenuHeadingFactory(slug="help")
        page = PageFactory()
        response = self.client.patch(f"/api/v1/management/pages/{page.slug}/", {"menu_heading": "help"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        page.refresh_from_db()
        assert page.menu_heading is not None and page.menu_heading.slug == "help"

        response = self.client.patch(f"/api/v1/management/pages/{page.slug}/", {"menu_heading": None}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        page.refresh_from_db()
        assert page.menu_heading is None

    def test_cannot_assign_unknown_menu_heading(self):
        page = PageFactory()
        response = self.client.patch(
            f"/api/v1/management/pages/{page.slug}/", {"menu_heading": "missing"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class MenuHeadingManagementAPITestCase(APITestCase):
    def setUp(self):
        self.superuser = SuperuserFactory()
        self.client.force_authenticate(self.superuser)

    def test_create_menu_heading(self):
        payload = {"slug": "help", "title": {"en": "Help", "fr": "Aide"}}
        response = self.client.post("/api/v1/management/menu-headings/", payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert MenuHeading.objects.filter(slug="help").exists()

    def test_cannot_create_menu_heading_with_reserved_slug(self):
        # "about" is the built-in heading's key in the nav order.
        payload = {"slug": "about", "title": {"en": "About"}}
        response = self.client.post("/api/v1/management/menu-headings/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data

    def test_cannot_create_menu_heading_with_uppercase_slug(self):
        # The frontend's `heading:<slug>` nav-order keys are lowercase-only.
        payload = {"slug": "Help", "title": {"en": "Help"}}
        response = self.client.post("/api/v1/management/menu-headings/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert not MenuHeading.objects.exists()

    def test_rename_title_but_not_slug(self):
        MenuHeadingFactory(slug="help")
        response = self.client.patch(
            "/api/v1/management/menu-headings/help/", {"title": {"en": "Guides"}}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        response = self.client.patch("/api/v1/management/menu-headings/help/", {"slug": "guides"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data

    def test_deleting_heading_moves_its_pages_back_to_about(self):
        heading = MenuHeadingFactory(slug="help")
        page = PageFactory(menu_heading=heading)
        response = self.client.delete("/api/v1/management/menu-headings/help/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        page.refresh_from_db()
        assert page.menu_heading is None
