"""One editable display order per hand, in place of `num`, `priority` and `is_default`.

Each part's hands are numbered 1, 2, … in the order the three columns gave them, so no list
changes order. Reversing restores the columns, with `num` holding the display order.
"""

from django.db import migrations, models


def number_each_parts_hands(apps, schema_editor):
    Hand = apps.get_model("scribes", "Hand")
    hands = Hand.objects.order_by("item_part", "-is_default", "-priority", "display_order", "name", "id")
    changed = []
    part, position = None, 0
    for hand in hands.only("id", "item_part_id", "display_order"):
        position = position + 1 if hand.item_part_id == part else 1
        part = hand.item_part_id
        if hand.display_order != position:
            hand.display_order = position
            changed.append(hand)
    Hand.objects.bulk_update(changed, ["display_order"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("scribes", "0018_remove_hand_description"),
    ]

    operations = [
        migrations.RenameField(model_name="hand", old_name="num", new_name="display_order"),
        migrations.RunPython(number_each_parts_hands, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="hand",
            options={"ordering": ["item_part", "display_order", "name", "id"]},
        ),
        migrations.RemoveField(model_name="hand", name="priority"),
        migrations.RemoveField(model_name="hand", name="is_default"),
        migrations.AlterField(
            model_name="hand",
            name="display_order",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Where this hand comes among its part's hands; lower comes first, and the first is "
                "the viewer's default for a new annotation.",
                verbose_name="Display order",
            ),
        ),
    ]
