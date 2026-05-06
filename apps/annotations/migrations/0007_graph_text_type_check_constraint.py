"""Permit TEXT-typed Graph rows under the editorial-or-required check.

Migration 0006 made allograph and hand nullable but the accompanying
CHECK constraint only allowed null FKs when annotation_type=editorial.
TEXT-typed graphs (regions on an image referenced from ImageText.content
via data-graph-id attributes) need the same exemption — they have no
glyph allograph and no scribal hand to attribute.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("annotations", "0006_graph_notes_and_editorial_optional_links"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="graph",
            name="graph_editorial_or_required_allograph_hand",
        ),
        migrations.AddConstraint(
            model_name="graph",
            constraint=models.CheckConstraint(
                condition=models.Q(annotation_type__in=["editorial", "text"])
                | (models.Q(allograph__isnull=False) & models.Q(hand__isnull=False)),
                name="graph_editorial_or_required_allograph_hand",
            ),
        ),
    ]
