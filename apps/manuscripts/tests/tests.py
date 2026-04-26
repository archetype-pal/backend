from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory, APITestCase

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory, ItemPartFactory

User = get_user_model()


class ItemPartAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.item_part = ItemPartFactory()

    def test_item_parts_list_returns_200(self):
        response = self.client.get("/api/v1/manuscripts/item-parts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertGreaterEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], self.item_part.id)

    def test_item_part_retrieve_returns_200(self):
        response = self.client.get(f"/api/v1/manuscripts/item-parts/{self.item_part.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.item_part.id)


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


class PublicImageTextViewSetTestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.item_image = ItemImageFactory()
        self.live = ImageTextFactory(item_image=self.item_image, status=ImageText.Status.LIVE)
        self.reviewed = ImageTextFactory(item_image=self.item_image, status=ImageText.Status.REVIEWED)
        self.draft = ImageTextFactory(item_image=self.item_image, status=ImageText.Status.DRAFT)
        self.review = ImageTextFactory(item_image=self.item_image, status=ImageText.Status.REVIEW)

    def test_anonymous_only_sees_live_and_reviewed(self):
        response = self.client.get(f"/api/v1/manuscripts/image-texts/?item_image={self.item_image.id}")
        assert response.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in response.data["results"]}
        assert ids == {self.live.id, self.reviewed.id}

    def test_staff_sees_all_statuses(self):
        staff = User.objects.create_user(username="staff", password="x", is_staff=True)
        self.client.force_authenticate(user=staff)
        response = self.client.get(f"/api/v1/manuscripts/image-texts/?item_image={self.item_image.id}")
        assert response.status_code == status.HTTP_200_OK
        ids = {row["id"] for row in response.data["results"]}
        assert ids == {self.live.id, self.reviewed.id, self.draft.id, self.review.id}

    def test_retrieve_returns_full_payload(self):
        response = self.client.get(f"/api/v1/manuscripts/image-texts/{self.live.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == self.live.id
        assert response.data["item_image"] == self.item_image.id
        assert "content" in response.data
        assert "status" in response.data

    def test_retrieve_draft_anonymous_is_404(self):
        response = self.client.get(f"/api/v1/manuscripts/image-texts/{self.draft.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
