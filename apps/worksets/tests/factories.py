import factory

from apps.users.tests.factories import UserFactory

from ..models import Workset

SAMPLE_PAYLOAD = {
    "schema_version": 2,
    "workspaces": [{"id": "ws-1", "name": "Charters", "currentWorkspaceId": "ws-1"}],
    "images": [{"id": "img-1", "originalId": 42, "type": "manuscript"}],
}


class WorksetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Workset

    owner = factory.SubFactory(UserFactory)
    title = factory.Sequence(lambda n: f"Workset {n}")
    description = ""
    visibility = Workset.Visibility.PRIVATE
    payload = factory.LazyFunction(lambda: dict(SAMPLE_PAYLOAD))
