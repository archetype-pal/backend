from django.db import migrations


def copy_place_text_to_place_ref(apps, schema_editor):
    """Fold free-text Hand.place values into the new Place authority list.

    Case-insensitive lookup/creation so "London" and "london" (or existing
    duplicates) collapse onto the same Place row instead of each minting a
    new one.
    """
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


def noop_reverse(apps, schema_editor):
    # Forward-only data fold; reversing would need to decide whether to
    # write the Place name back into the text field, which the schema
    # migration after this one already makes impossible (place_ref is
    # renamed over place). Nothing to undo here on its own.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('scribes', '0012_hand_place_ref'),
    ]

    operations = [
        migrations.RunPython(copy_place_text_to_place_ref, noop_reverse),
    ]
