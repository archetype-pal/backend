import pytest

from apps.scribes.models import Script
from apps.scribes.tests.factories import HandFactory, ScriptFactory


@pytest.mark.django_db
class TestScriptManagementViewSet:
    def _url(self, pk=None):
        base = "/api/v1/management/scribes/scripts/"
        return f"{base}{pk}/" if pk else base

    def test_list_is_unpaginated_and_ordered_by_name(self, management_client):
        ScriptFactory(name="Square minuscule")
        ScriptFactory(name="Caroline minuscule")

        response = management_client.get(self._url())

        assert response.status_code == 200
        assert [row["name"] for row in response.json()] == ["Caroline minuscule", "Square minuscule"]

    def test_create_update_and_delete(self, management_client):
        created = management_client.post(self._url(), data={"name": "Caroline miniscule"}, format="json")
        assert created.status_code == 201, created.json()
        script_id = created.json()["id"]

        updated = management_client.patch(self._url(script_id), data={"name": "Caroline minuscule"}, format="json")
        assert updated.status_code == 200
        assert Script.objects.get(pk=script_id).name == "Caroline minuscule"

        deleted = management_client.delete(self._url(script_id))
        assert deleted.status_code == 204
        assert not Script.objects.filter(pk=script_id).exists()

    def test_delete_is_blocked_when_a_hand_uses_the_script(self, management_client):
        hand = HandFactory(script=ScriptFactory(name="Caroline minuscule"))

        response = management_client.delete(self._url(hand.script_id))

        assert response.status_code == 409
        assert response.json()["detail"] == "Cannot delete: still referenced by 1 hand."
        assert Script.objects.filter(pk=hand.script_id).exists()
