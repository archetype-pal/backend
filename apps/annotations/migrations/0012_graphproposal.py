# The annotation write gate (AI programme W0.5). A staging table rather than a
# status column on Graph: the canonical table simply never contains an
# unreviewed row, so no read path can leak one by forgetting a filter.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('annotations', '0011_alter_graph_options_alter_graph_managers'),
        ('manuscripts', '0027_reproduction_rights'),
        ('ml', '0001_initial'),
        ('scribes', '0010_alter_hand_date_alter_hand_item_part_images'),
        ('symbols_structure', '0008_allographposition_allograph_positions_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GraphProposal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('annotation', models.JSONField()),
                ('annotation_type', models.CharField(choices=[('image', 'Image'), ('text', 'Text'), ('editorial', 'Editorial'), ('unknown', 'Unknown')], default='image', max_length=20)),
                ('confidence', models.FloatField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')], db_index=True, default='pending', max_length=16)),
                ('reviewed', models.DateTimeField(blank=True, null=True)),
                ('reason', models.TextField(blank=True, default='')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('accepted_graph', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='annotations.graph')),
                ('allograph', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='symbols_structure.allograph')),
                ('hand', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='scribes.hand')),
                ('item_image', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='graph_proposals', to='manuscripts.itemimage')),
                ('ml_job', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='graph_proposals', to='ml.mljob')),
                ('reviewer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='graph_proposals_reviewed', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created'],
                'indexes': [models.Index(fields=['item_image', 'status'], name='proposal_image_status_idx')],
            },
        ),
    ]
