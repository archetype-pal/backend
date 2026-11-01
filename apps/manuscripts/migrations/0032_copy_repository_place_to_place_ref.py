from django.db import migrations


def copy_place_text_to_place_ref(apps, schema_editor):
    Repository = apps.get_model('manuscripts', 'Repository')
    Place = apps.get_model('common', 'Place')

    cache = {}
    for repository in Repository.objects.exclude(place='').only('id', 'place'):
        name = repository.place.strip()
        if not name:
            continue
        lookup_key = name.lower()
        place = cache.get(lookup_key)
        if place is None:
            place = Place.objects.filter(name__iexact=name).first() or Place.objects.create(name=name)
            cache[lookup_key] = place
        Repository.objects.filter(pk=repository.pk).update(place_ref=place)


def copy_place_ref_to_place_text(apps, schema_editor):
    Repository = apps.get_model('manuscripts', 'Repository')
    for repository in Repository.objects.exclude(place_ref=None).select_related('place_ref'):
        Repository.objects.filter(pk=repository.pk).update(place=repository.place_ref.name[:50])


class Migration(migrations.Migration):

    dependencies = [
        ('manuscripts', '0031_repository_place_ref'),
    ]

    operations = [
        migrations.RunPython(copy_place_text_to_place_ref, copy_place_ref_to_place_text),
    ]
