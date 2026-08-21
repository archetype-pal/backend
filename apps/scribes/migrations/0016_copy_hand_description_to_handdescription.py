from django.db import migrations


def copy_description_text_to_handdescription(apps, schema_editor):
    """Fold the old single free-text Hand.description into one HandDescription row.

    No source is known for this legacy text, so `source` is left null — the
    same "known content, unknown citation" gap the reporter flagged.
    """
    Hand = apps.get_model('scribes', 'Hand')
    HandDescription = apps.get_model('scribes', 'HandDescription')

    HandDescription.objects.bulk_create(
        HandDescription(hand_id=hand.pk, content=hand.description)
        for hand in Hand.objects.exclude(description='').only('id', 'description')
    )


def noop_reverse(apps, schema_editor):
    # Forward-only data fold; the schema migration after this one removes
    # the field being folded from, so there is nothing to reverse into.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('scribes', '0015_hand_description_model'),
    ]

    operations = [
        migrations.RunPython(copy_description_text_to_handdescription, noop_reverse),
    ]
