# Evaluation runs (AI programme W0.3). `release`, `split`, `baseline_name` and
# `baseline_metrics` are non-nullable on purpose: the release rule is that no
# number ships without its split and its baseline, and a nullable column is an
# invitation to ship one that does.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ml', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='EvaluationRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('model_name', models.CharField(max_length=128)),
                ('model_version', models.CharField(blank=True, default='', max_length=128)),
                ('task', models.CharField(db_index=True, max_length=64)),
                ('release', models.CharField(max_length=64)),
                ('split', models.CharField(max_length=32)),
                ('metrics', models.JSONField()),
                ('baseline_name', models.CharField(max_length=64)),
                ('baseline_metrics', models.JSONField()),
                ('notes', models.TextField(blank=True, default='')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'ordering': ['-created'],
                'indexes': [models.Index(fields=['task', '-created'], name='evalrun_task_created_idx')],
            },
        ),
    ]
