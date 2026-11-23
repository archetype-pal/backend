from collections import defaultdict

from django.db import migrations


def copy_assessments_to_items(apps, schema_editor):
    HistoricalItem = apps.get_model('manuscripts', 'HistoricalItem')
    HistoricalItemDateAssessment = apps.get_model('manuscripts', 'HistoricalItemDateAssessment')

    rows_by_item = defaultdict(list)
    for row in HistoricalItemDateAssessment.objects.select_related('date').order_by('id'):
        rows_by_item[row.historical_item_id].append(row)

    for item in HistoricalItem.objects.filter(pk__in=list(rows_by_item)).only('id', 'date_id'):
        rows = rows_by_item[item.pk]
        matching = next((row for row in rows if row.date_id == item.date_id), None)
        notes = [matching.dating_notes] if matching and matching.dating_notes else []
        for row in rows:
            if row is matching:
                continue
            parts = [row.dating_notes] if row.dating_notes else []
            if row.probable_text_date:
                parts.append(f'Probable text date: {row.probable_text_date}')
            if parts:
                notes.append(f'{row.date.date}: ' + '\n'.join(parts))
        HistoricalItem.objects.filter(pk=item.pk).update(
            probable_text_date=matching.probable_text_date if matching else '',
            dating_notes='\n\n'.join(notes),
        )


def copy_items_to_assessments(apps, schema_editor):
    HistoricalItem = apps.get_model('manuscripts', 'HistoricalItem')
    HistoricalItemDateAssessment = apps.get_model('manuscripts', 'HistoricalItemDateAssessment')

    dated_items = HistoricalItem.objects.exclude(date=None).values_list(
        'id', 'date_id', 'probable_text_date', 'dating_notes'
    )
    for item_id, date_id, probable_text_date, dating_notes in dated_items:
        rows = HistoricalItemDateAssessment.objects.filter(historical_item_id=item_id)
        if not probable_text_date and not dating_notes:
            rows.delete()
            continue
        rows.exclude(date_id=date_id).delete()
        HistoricalItemDateAssessment.objects.update_or_create(
            historical_item_id=item_id,
            date_id=date_id,
            defaults={'probable_text_date': probable_text_date, 'dating_notes': dating_notes},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('manuscripts', '0036_historicalitem_probable_text_date_dating_notes'),
    ]

    operations = [
        migrations.RunPython(copy_assessments_to_items, copy_items_to_assessments),
    ]
