from django.db import migrations


def copy_description_text_to_handdescription(apps, schema_editor):
    Hand = apps.get_model('scribes', 'Hand')
    HandDescription = apps.get_model('scribes', 'HandDescription')

    HandDescription.objects.bulk_create(
        HandDescription(hand_id=hand.pk, content=hand.description)
        for hand in Hand.objects.exclude(description='').only('id', 'description')
    )


def copy_first_handdescription_to_description_text(apps, schema_editor):
    """Only the first description per hand fits back into the single text field."""
    Hand = apps.get_model('scribes', 'Hand')
    HandDescription = apps.get_model('scribes', 'HandDescription')

    seen = set()
    for description in HandDescription.objects.order_by('hand_id', 'id').only('hand_id', 'content'):
        if description.hand_id in seen:
            continue
        seen.add(description.hand_id)
        Hand.objects.filter(pk=description.hand_id).update(description=description.content)


class Migration(migrations.Migration):

    dependencies = [
        ('scribes', '0016_hand_description_model'),
    ]

    operations = [
        migrations.RunPython(copy_description_text_to_handdescription, copy_first_handdescription_to_description_text),
    ]
