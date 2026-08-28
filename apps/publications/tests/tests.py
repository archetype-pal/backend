from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.publications.models import Partner, Publication
from apps.publications.tests.factories import CarouselItemFactory, EventFactory, PartnerFactory, PublicationFactory
from apps.users.tests.factories import UserFactory


def _tiny_image(name="logo.png"):
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


class CarouselItemAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.carousel_items = CarouselItemFactory.create_batch(3)

    def test_carousel_items_api(self):
        response = self.client.get("/api/v1/media/carousel-items/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3, response.data


class PartnerAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.partners = PartnerFactory.create_batch(3)

    def test_partners_api(self):
        response = self.client.get("/api/v1/media/partners/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3, response.data
        assert {"id", "name", "url", "logo", "ordering"} <= set(response.data[0].keys())


class PartnerManagementAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_authenticate(self.superuser)

    def test_create_partner(self):
        payload = {"name": "Test Partner", "url": "https://example.org", "logo": _tiny_image()}
        response = self.client.post("/api/v1/media/management/partners/", payload, format="multipart")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Partner.objects.filter(name="Test Partner").exists()

    def test_update_partner_ordering(self):
        partner = PartnerFactory()
        response = self.client.patch(f"/api/v1/media/management/partners/{partner.id}/", {"ordering": 5}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        partner.refresh_from_db()
        assert partner.ordering == 5

    def test_delete_partner(self):
        partner = PartnerFactory()
        response = self.client.delete(f"/api/v1/media/management/partners/{partner.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Partner.objects.filter(id=partner.id).exists()

    def test_anonymous_cannot_write(self):
        self.client.force_authenticate(None)
        response = self.client.post(
            "/api/v1/media/management/partners/",
            {"name": "x", "url": "", "logo": _tiny_image()},
            format="multipart",
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


class PublicationManagementAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_authenticate(self.superuser)

    def test_create_draft_with_minimal_payload_assigns_author(self):
        response = self.client.post(
            "/api/v1/media/management/publications/",
            {"title": "Draft Shell", "slug": "draft-shell"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        publication = Publication.objects.get(slug="draft-shell")
        assert publication.author == self.superuser
        assert publication.status == Publication.Status.DRAFT
        assert publication.content == ""
        assert publication.preview == ""
        assert response.data["author"] == self.superuser.id

    def test_create_ignores_client_supplied_author(self):
        other_user = UserFactory(is_staff=True, is_superuser=True)

        response = self.client.post(
            "/api/v1/media/management/publications/",
            {"title": "Owned Draft", "slug": "owned-draft", "author": other_user.id},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        publication = Publication.objects.get(slug="owned-draft")
        assert publication.author == self.superuser
        assert response.data["author"] == self.superuser.id

    def test_create_published_requires_content_and_preview(self):
        response = self.client.post(
            "/api/v1/media/management/publications/",
            {
                "title": "Incomplete Published Post",
                "slug": "incomplete-published-post",
                "status": Publication.Status.PUBLISHED,
                "content": "<p><br></p>",
                "preview": "<p>&nbsp;</p>",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "content" in response.data
        assert "preview" in response.data

    def test_update_to_published_requires_content_and_preview(self):
        publication = PublicationFactory(
            author=self.superuser,
            status=Publication.Status.DRAFT,
            content="",
            preview="",
        )

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"status": Publication.Status.PUBLISHED},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "content" in response.data
        assert "preview" in response.data

    def test_update_to_published_with_content_and_preview_succeeds(self):
        publication = PublicationFactory(
            author=self.superuser,
            status=Publication.Status.DRAFT,
            content="",
            preview="",
        )

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {
                "status": Publication.Status.PUBLISHED,
                "content": "<p>Body text</p>",
                "preview": "<p>Preview text</p>",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        publication.refresh_from_db()
        assert publication.status == Publication.Status.PUBLISHED
        assert publication.content == "<p>Body text</p>"
        assert publication.preview == "<p>Preview text</p>"

    def test_keywords_round_trip_as_a_string(self):
        publication = PublicationFactory(author=self.superuser)

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"keywords": "charters, scribes"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        # The response must show the new tags, not the pre-write state.
        assert response.data["keywords"] == "charters, scribes"
        # Re-fetch rather than refresh_from_db(): the latter drops Tagulous'
        # tag-string cache without repopulating it, so str() would read blank.
        assert str(Publication.objects.get(pk=publication.pk).keywords) == "charters, scribes"

    def test_too_many_keywords_is_rejected_with_400(self):
        """Tagulous raises a bare ValueError on save once max_count is passed,
        which would surface as a 500. The field has to catch it first."""
        publication = PublicationFactory(author=self.superuser)
        max_count = Publication._meta.get_field("keywords").tag_options.max_count

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"keywords": ", ".join(f"k{i}" for i in range(max_count + 1))},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert "keywords" in response.data
        publication.refresh_from_db()
        assert publication.keywords.count() == 0

    def test_keyword_count_follows_tagulous_space_delimiting(self):
        """Spaces delimit tags too, so counting commas would let a payload
        through that the save then rejects."""
        publication = PublicationFactory(author=self.superuser)

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"keywords": "a b c d e f g h i j k"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data

    def test_blank_keywords_clears_the_tags(self):
        publication = PublicationFactory(author=self.superuser)
        publication.keywords = "one, two"
        publication.save()

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"keywords": ""},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["keywords"] == ""
        publication.refresh_from_db()
        assert publication.keywords.count() == 0

    def test_create_accepts_keywords(self):
        response = self.client.post(
            "/api/v1/media/management/publications/",
            {"title": "Tagged", "slug": "tagged", "keywords": "alpha, beta"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Publication.objects.get(slug="tagged").keywords.count() == 2


class EventsAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.events = EventFactory.create_batch(3)

    def test_events_list_api(self):
        response = self.client.get("/api/v1/media/events/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3, response.data

    def test_events_detail_api(self):
        event = self.events[0]
        response = self.client.get(f"/api/v1/media/events/{event.slug}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == event.slug
        assert response.data["title"] == event.title


class PublicationsAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.publications = PublicationFactory.create_batch(3)

    def test_publications_list_api(self):
        publication = self.publications[0]
        publication.keywords = "palaeography, medieval"
        publication.save()

        response = self.client.get("/api/v1/media/publications/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3, response.data
        result = next(r for r in response.data["results"] if r["id"] == publication.id)
        assert "keywords" in result
        assert "palaeography" in result["keywords"]

    def test_publication_detail_api(self):
        publication = self.publications[0]
        publication.keywords = "charters, scribes"
        publication.save()

        response = self.client.get(f"/api/v1/media/publications/{publication.slug}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == publication.slug
        assert response.data["title"] == publication.title
        assert "keywords" in response.data
        assert "charters" in response.data["keywords"]

    def test_publications_list_does_not_query_keywords_per_row(self):
        """`keywords` is a m2m, so serializing it without a prefetch costs one
        query per publication."""
        for index, publication in enumerate(self.publications):
            publication.keywords = f"alpha{index}, beta{index}"
            publication.save()

        with CaptureQueriesContext(connection) as three_rows:
            assert self.client.get("/api/v1/media/publications/").status_code == status.HTTP_200_OK

        PublicationFactory.create_batch(3)
        with CaptureQueriesContext(connection) as six_rows:
            assert self.client.get("/api/v1/media/publications/").status_code == status.HTTP_200_OK

        assert len(six_rows.captured_queries) == len(three_rows.captured_queries), (
            f"query count grew with row count: {len(three_rows.captured_queries)} -> {len(six_rows.captured_queries)}"
        )
