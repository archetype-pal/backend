from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory, APITestCase

from apps.manuscripts.tests.factories import ItemImageFactory, ItemPartFactory


class ItemImageAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.factory = APIRequestFactory()
        self.item_part = ItemPartFactory()
        ItemImageFactory.create_batch(3, item_part=self.item_part)

    def test_images_api(self):
        response = self.client.get(f"/api/v1/manuscripts/item-images/?item_part={self.item_part.id}")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3, response.data
        assert response.data["results"][0]["item_part"] == self.item_part.id
        assert response.data["results"][0]["locus"] == self.item_part.images.first().locus

    def test_retrieve_item_image(self):
        item_image = self.item_part.images.first()
        response = self.client.get(f"/api/v1/manuscripts/item-images/{item_image.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["item_part"] == self.item_part.id
        assert response.data["locus"] == item_image.locus
