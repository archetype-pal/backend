import factory


class ScriptFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "scribes.Script"

    name = factory.Faker("random_element", elements=["English", "Latin", "Greek"])


class ScribeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "scribes.Scribe"

    name = factory.Faker("name")
    period = factory.Faker("century")
    scriptorium = factory.Faker("word")


class HandFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "scribes.Hand"

    name = factory.Faker("name")
    scribe = factory.SubFactory(ScribeFactory)
    script = factory.SubFactory(ScriptFactory)
    item_part = factory.SubFactory("apps.manuscripts.tests.factories.ItemPartFactory")
    date = factory.SubFactory("apps.common.tests.factories.DateFactory")
    place = factory.Faker("city")
    description = factory.Faker("text")
