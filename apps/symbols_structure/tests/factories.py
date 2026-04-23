import factory

from apps.symbols_structure.models import Allograph, AllographComponent, AllographComponentFeature, Character


class CharacterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Character

    name = factory.Faker("random_lowercase_letter")
    type = "Minuscule Letter"


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


class AllographComponentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AllographComponent

    allograph = factory.SubFactory(AllographFactory)
    component = factory.SubFactory(ComponentFactory)


class AllographComponentFeatureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AllographComponentFeature

    allograph_component = factory.SubFactory(AllographComponentFactory)
    feature = factory.SubFactory(FeatureFactory)
    set_by_default = False


class AllographPositionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "symbols_structure.AllographPosition"

    allograph = factory.SubFactory(AllographFactory)
    position = factory.SubFactory(PositionFactory)
