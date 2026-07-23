import factory

from apps.manuscripts.tests.factories import ItemPartFactory
from apps.uploads.models import UploadSession
from apps.users.tests.factories import SuperuserFactory


class UploadSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UploadSession

    owner = factory.SubFactory(SuperuserFactory)
    item_part = factory.SubFactory(ItemPartFactory)
    original_filename = "page.tif"
    declared_size = 12
    chunk_size = 4
    destination_path = factory.Sequence(lambda n: f"uploads/item-part-test/page-{n}.jp2")
