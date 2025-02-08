import factory

from apps.symbols_structure.models import Allograph, Character


class CharacterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Character

    name = factory.Faker("random_lowercase_letter")
    type = Character.CharacterForm.MINUSCULE_LETTER


class AllographFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Allograph

    character = factory.SubFactory(CharacterFactory)
    name = factory.Faker("random_lowercase_letter")


class FeatureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "symbols_structure.Feature"

    name = factory.Sequence(lambda n: f"feature_{n}")


class ComponentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "symbols_structure.Component"

    name = factory.Sequence(lambda n: f"component_{n}")


class PositionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "symbols_structure.Position"

    name = factory.Sequence(lambda n: f"position_{n}")
