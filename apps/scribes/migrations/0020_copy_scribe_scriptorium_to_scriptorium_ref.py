from django.db import migrations


def copy_scriptorium_text_to_scriptorium_ref(apps, schema_editor):
    Scribe = apps.get_model('scribes', 'Scribe')
    Place = apps.get_model('common', 'Place')

    cache = {}
    for scribe in Scribe.objects.exclude(scriptorium='').only('id', 'scriptorium'):
        name = scribe.scriptorium.strip()
        if not name:
            continue
        lookup_key = name.lower()
        place = cache.get(lookup_key)
        if place is None:
            place = Place.objects.filter(name__iexact=name).first() or Place.objects.create(name=name)
            cache[lookup_key] = place
        Scribe.objects.filter(pk=scribe.pk).update(scriptorium_ref=place)


def copy_scriptorium_ref_to_scriptorium_text(apps, schema_editor):
    Scribe = apps.get_model('scribes', 'Scribe')
    for scribe in Scribe.objects.exclude(scriptorium_ref=None).select_related('scriptorium_ref'):
        Scribe.objects.filter(pk=scribe.pk).update(scriptorium=scribe.scriptorium_ref.name[:100])


class Migration(migrations.Migration):

    dependencies = [
        ('scribes', '0019_scribe_scriptorium_ref'),
    ]

    operations = [
        migrations.RunPython(copy_scriptorium_text_to_scriptorium_ref, copy_scriptorium_ref_to_scriptorium_text),
    ]
