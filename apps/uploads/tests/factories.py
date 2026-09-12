import factory

from apps.manuscripts.tests.factories import ItemPartFactory
from apps.uploads.models import ImageUploadSession
from apps.users.tests.factories import SuperuserFactory


class ImageUploadSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImageUploadSession

    owner = factory.SubFactory(SuperuserFactory)
    item_part = factory.SubFactory(ItemPartFactory)
    original_filename = "page.tif"
    declared_size = 12
    chunk_size = 4
    destination_path = factory.Sequence(lambda n: f"uploads/item-part-test/page-{n}.jp2")
