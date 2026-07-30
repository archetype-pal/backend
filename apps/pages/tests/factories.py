import factory
from factory.django import DjangoModelFactory

from apps.pages.models import Page


class PageFactory(DjangoModelFactory):
    class Meta:
        model = Page

    slug = factory.Sequence(lambda n: f"sample-page-{n}")
    title = factory.LazyFunction(lambda: {"en": "Sample title", "fr": "Titre exemple"})
    content = factory.LazyFunction(lambda: {"en": "<p>Sample content</p>", "fr": "<p>Contenu exemple</p>"})
    status = Page.Status.PUBLISHED
