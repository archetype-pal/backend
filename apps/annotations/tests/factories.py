import factory

from apps.annotations.models import Graph, GraphComponent


class GraphFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Graph

    item_image = factory.SubFactory("apps.manuscripts.tests.factories.ItemImageFactory")
    allograph = factory.SubFactory("apps.symbols_structure.tests.factories.AllographFactory")
    hand = factory.SubFactory("apps.scribes.tests.factories.HandFactory")
    annotation = {"test": "test"}


class GraphComponentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GraphComponent

    graph = factory.SubFactory(GraphFactory)
    component = factory.SubFactory("apps.symbols_structure.tests.factories.ComponentFactory")
