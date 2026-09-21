from io import BytesIO
import os

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.common.views import MAX_LOGO_UPLOAD_SIZE
from apps.users.tests.factories import SuperuserFactory, UserFactory

URL = "/api/v1/app-settings/branding/logo/"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _tiny_image(name="logo.png", content_type="image/png"):
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type=content_type)


@pytest.mark.django_db
class TestBrandingLogoUpload:
    def test_superuser_can_upload_a_logo(self):
        client = client_for(SuperuserFactory())
        response = client.post(URL, {"logo": _tiny_image()}, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        url = response.data["url"]
        assert "branding/" in url

        # The file was actually written to storage, not just described.
        filename = url.rsplit("/", 1)[-1]
        _, filenames = default_storage.listdir("branding")
        assert filename in filenames

    def test_anonymous_cannot_upload(self):
        response = APIClient().post(URL, {"logo": _tiny_image()}, format="multipart")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_superuser_cannot_upload(self):
        client = client_for(UserFactory())
        response = client.post(URL, {"logo": _tiny_image()}, format="multipart")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_image_file_is_rejected(self):
        client = client_for(SuperuserFactory())
        not_an_image = SimpleUploadedFile("logo.txt", b"not an image", content_type="text/plain")
        response = client.post(URL, {"logo": not_an_image}, format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_oversized_file_is_rejected(self):
        client = client_for(SuperuserFactory())
        buf = BytesIO()
        # A real image comfortably over the limit, not just a padded byte
        # string — a bad size check bypass (e.g. reading Content-Length
        # instead of the decoded image) must still be caught. Random noise,
        # saved uncompressed (BMP), so it can't be squashed below the limit.
        noise = Image.frombytes("RGB", (2000, 2000), os.urandom(2000 * 2000 * 3))
        noise.save(buf, format="BMP")
        assert buf.tell() > MAX_LOGO_UPLOAD_SIZE
        buf.seek(0)
        oversized = SimpleUploadedFile("logo.bmp", buf.read(), content_type="image/bmp")
        response = client.post(URL, {"logo": oversized}, format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_file_is_rejected(self):
        client = client_for(SuperuserFactory())
        response = client.post(URL, {}, format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
