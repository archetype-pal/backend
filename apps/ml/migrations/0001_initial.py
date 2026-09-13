# The inference ledger (W0.1). Two tables and no foreign key into a domain
# app: `MLJobTarget` points at records with loose (target_type, target_id)
# pairs, so provenance outlives the record it describes and `apps.ml` keeps
# its declared dependency on `common` alone.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MLJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task', models.CharField(db_index=True, max_length=64)),
                ('provider', models.CharField(max_length=64)),
                ('model_name', models.CharField(blank=True, default='', max_length=128)),
                ('model_version', models.CharField(blank=True, default='', max_length=128)),
                ('prompt_hash', models.CharField(blank=True, default='', max_length=64)),
                ('input_ref', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('params', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('succeeded', 'Succeeded'), ('failed', 'Failed'), ('refused', 'Refused')], default='pending', max_length=16)),
                ('error', models.TextField(blank=True, default='')),
                ('input_tokens', models.PositiveIntegerField(default=0)),
                ('output_tokens', models.PositiveIntegerField(default=0)),
                ('cost_micros', models.BigIntegerField(default=0)),
                ('cost_currency', models.CharField(blank=True, default='', max_length=3)),
                ('celery_task_id', models.CharField(blank=True, default='', max_length=64)),
                ('duration_ms', models.PositiveIntegerField(blank=True, null=True)),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ml_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'ML job',
                'verbose_name_plural': 'ML jobs',
                'ordering': ['-created'],
            },
        ),
        migrations.CreateModel(
            name='MLJobTarget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_type', models.CharField(max_length=64)),
                ('target_id', models.BigIntegerField()),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='targets', to='ml.mljob')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
        migrations.AddIndex(
            model_name='mljob',
            index=models.Index(fields=['task', '-created'], name='mljob_task_created_idx'),
        ),
        migrations.AddIndex(
            model_name='mljob',
            index=models.Index(fields=['status', '-created'], name='mljob_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='mljob',
            index=models.Index(fields=['actor', '-created'], name='mljob_actor_created_idx'),
        ),
        migrations.AddIndex(
            model_name='mljobtarget',
            index=models.Index(fields=['target_type', 'target_id'], name='mljobtarget_target_idx'),
        ),
        migrations.AddConstraint(
            model_name='mljobtarget',
            constraint=models.UniqueConstraint(fields=('job', 'target_type', 'target_id'), name='unique_ml_job_target'),
        ),
    ]
