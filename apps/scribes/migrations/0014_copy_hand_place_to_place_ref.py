from django.db import migrations


def copy_place_text_to_place_ref(apps, schema_editor):
    Hand = apps.get_model('scribes', 'Hand')
    Place = apps.get_model('common', 'Place')

    cache = {}
    for hand in Hand.objects.exclude(place='').only('id', 'place'):
        name = hand.place.strip()
        if not name:
            continue
        lookup_key = name.lower()
        place = cache.get(lookup_key)
        if place is None:
            place = Place.objects.filter(name__iexact=name).first() or Place.objects.create(name=name)
            cache[lookup_key] = place
        Hand.objects.filter(pk=hand.pk).update(place_ref=place)


def copy_place_ref_to_place_text(apps, schema_editor):
    Hand = apps.get_model('scribes', 'Hand')
    for hand in Hand.objects.exclude(place_ref=None).select_related('place_ref'):
        Hand.objects.filter(pk=hand.pk).update(place=hand.place_ref.name)


class Migration(migrations.Migration):

    dependencies = [
        ('scribes', '0013_hand_place_ref'),
    ]

    operations = [
        migrations.RunPython(copy_place_text_to_place_ref, copy_place_ref_to_place_text),
    ]
