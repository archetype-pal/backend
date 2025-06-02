from datetime import timezone

import factory
from factory.django import DjangoModelFactory

from apps.publications.models import CarouselItem, Event, Publication


class CarouselItemFactory(DjangoModelFactory):
    class Meta:
        model = CarouselItem

    image = factory.django.ImageField()
    title = factory.Faker("sentence", nb_words=4)
    url = factory.Faker("url")


class EventFactory(DjangoModelFactory):
    class Meta:
        model = Event

    title = factory.Faker("sentence", nb_words=4)
    slug = factory.Faker("slug")
    content = factory.Faker("text")


class PublicationFactory(DjangoModelFactory):
    class Meta:
        model = Publication

    title = factory.Faker("sentence", nb_words=4)
    slug = factory.Faker("slug")
    content = factory.Faker("text")
    preview = factory.Faker("sentence", nb_words=20)
    status = Publication.Status.PUBLISHED
    is_blog_post = factory.Faker("boolean")
    is_news = factory.Faker("boolean")
    is_featured = factory.Faker("boolean")
    published_at = factory.Faker("date_time_this_month", tzinfo=timezone.UTC)
    author = factory.SubFactory("apps.users.tests.factories.UserFactory")
