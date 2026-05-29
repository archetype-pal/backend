import pytest
from rest_framework.test import APIClient

from apps.common.permissions import IsOwnerOrReadOnly
from apps.users.tests.factories import UserFactory

from ..models import Workset
from .factories import SAMPLE_PAYLOAD, WorksetFactory

LIST_URL = "/api/v1/worksets/"


def detail_url(workset: Workset) -> str:
    return f"/api/v1/worksets/{workset.public_id}/"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestWorksetCrud:
    def test_anonymous_list_is_unauthorized(self, api_client):
        assert api_client.get(LIST_URL).status_code == 401

    def test_create_sets_owner_and_mints_public_id(self):
        user = UserFactory()
        client = client_for(user)
        response = client.post(
            LIST_URL,
            {"title": "My charters", "payload": SAMPLE_PAYLOAD},
            format="json",
        )
        assert response.status_code == 201
        workset = Workset.objects.get(public_id=response.data["public_id"])
        assert workset.owner == user
        assert workset.visibility == Workset.Visibility.PRIVATE  # safe default
        assert response.data["payload"] == SAMPLE_PAYLOAD

    def test_list_returns_only_callers_worksets(self):
        owner = UserFactory()
        WorksetFactory(owner=owner, title="mine")
        WorksetFactory(owner=UserFactory(), title="someone else's")
        response = client_for(owner).get(LIST_URL)
        assert response.status_code == 200
        titles = [row["title"] for row in response.data["results"]]
        assert titles == ["mine"]

    def test_owner_can_update_and_delete(self):
        owner = UserFactory()
        workset = WorksetFactory(owner=owner)
        client = client_for(owner)

        patch = client.patch(detail_url(workset), {"title": "Renamed"}, format="json")
        assert patch.status_code == 200
        workset.refresh_from_db()
        assert workset.title == "Renamed"

        assert client.delete(detail_url(workset)).status_code == 204
        assert not Workset.objects.filter(pk=workset.pk).exists()

    def test_non_owner_cannot_update_or_delete(self):
        workset = WorksetFactory(visibility=Workset.Visibility.PUBLIC)
        intruder = client_for(UserFactory())
        # Owner-scoped queryset hides it from non-owners → 404, no existence leak.
        assert intruder.patch(detail_url(workset), {"title": "hijack"}, format="json").status_code == 404
        assert intruder.delete(detail_url(workset)).status_code == 404
        workset.refresh_from_db()
        assert workset.title != "hijack"


@pytest.mark.django_db
class TestWorksetCitableReads:
    def test_anonymous_can_read_public_workset(self, api_client):
        workset = WorksetFactory(visibility=Workset.Visibility.PUBLIC)
        response = api_client.get(detail_url(workset))
        assert response.status_code == 200
        assert response.data["payload"] == workset.payload
        assert response.data["owner"]["username"] == workset.owner.username

    def test_anonymous_cannot_read_private_workset(self, api_client):
        workset = WorksetFactory(visibility=Workset.Visibility.PRIVATE)
        assert api_client.get(detail_url(workset)).status_code == 404

    def test_other_user_cannot_read_private_workset(self):
        workset = WorksetFactory(visibility=Workset.Visibility.PRIVATE)
        assert client_for(UserFactory()).get(detail_url(workset)).status_code == 404

    def test_owner_can_read_own_private_workset(self):
        owner = UserFactory()
        workset = WorksetFactory(owner=owner, visibility=Workset.Visibility.PRIVATE)
        assert client_for(owner).get(detail_url(workset)).status_code == 200


@pytest.mark.django_db
class TestWorksetPayloadGuard:
    def test_rejects_oversized_payload(self):
        client = client_for(UserFactory())
        big = {"schema_version": 2, "blob": "x" * (256 * 1024 + 10)}
        response = client.post(LIST_URL, {"title": "huge", "payload": big}, format="json")
        assert response.status_code == 400
        assert "payload" in response.data

    def test_rejects_non_object_payload(self):
        client = client_for(UserFactory())
        response = client.post(LIST_URL, {"title": "bad", "payload": [1, 2, 3]}, format="json")
        assert response.status_code == 400

    def test_rejects_oversized_description(self):
        client = client_for(UserFactory())
        response = client.post(
            LIST_URL,
            {"title": "x", "description": "y" * 4001, "payload": SAMPLE_PAYLOAD},
            format="json",
        )
        assert response.status_code == 400
        assert "description" in response.data


class TestIsOwnerOrReadOnlyPermission:
    class _Req:
        def __init__(self, method, user):
            self.method = method
            self.user = user

    class _Obj:
        def __init__(self, owner_id):
            self.owner_id = owner_id

    class _User:
        def __init__(self, uid):
            self.id = uid
            self.is_authenticated = True

    def test_safe_method_allowed_for_anyone(self):
        perm = IsOwnerOrReadOnly()
        req = self._Req("GET", self._User(2))
        assert perm.has_object_permission(req, None, self._Obj(owner_id=1)) is True

    def test_owner_allowed_for_writes(self):
        perm = IsOwnerOrReadOnly()
        req = self._Req("DELETE", self._User(1))
        assert perm.has_object_permission(req, None, self._Obj(owner_id=1)) is True

    def test_non_owner_denied_for_writes(self):
        perm = IsOwnerOrReadOnly()
        req = self._Req("PATCH", self._User(2))
        assert perm.has_object_permission(req, None, self._Obj(owner_id=1)) is False
