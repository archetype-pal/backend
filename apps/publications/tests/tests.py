from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.publications.tests.factories import CarouselItemFactory, EventFactory, PublicationFactory


class CarouselItemAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.carousel_items = CarouselItemFactory.create_batch(3)

    def test_carousel_items_api(self):
        response = self.client.get("/api/v1/media/carousel-items/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3, response.data


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
