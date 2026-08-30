import factory

from apps.ml.models import MLJob, MLJobTarget


class MLJobFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MLJob

    task = "W0.1"
    provider = "null"
    model_name = "null"
    model_version = "1"
    status = MLJob.Status.SUCCEEDED


class MLJobTargetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MLJobTarget

    job = factory.SubFactory(MLJobFactory)
    target_type = "graph"
    target_id = factory.Sequence(lambda n: n + 1)
