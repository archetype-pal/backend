from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.publications.models import Partner
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
        response = self.client.get("/api/v1/media/publications/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3, response.data

    def test_publication_detail_api(self):
        publication = self.publications[0]
        response = self.client.get(f"/api/v1/media/publications/{publication.slug}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == publication.slug
        assert response.data["title"] == publication.title
