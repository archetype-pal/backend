from django.db import migrations
from django.db.models import Count, Min


def merge_duplicate_scripts(apps, schema_editor):
    Script = apps.get_model("scribes", "Script")
    Hand = apps.get_model("scribes", "Hand")
    duplicated = Script.objects.order_by().values("name").annotate(keep=Min("pk"), n=Count("pk")).filter(n__gt=1)
    for row in duplicated:
        others = Script.objects.filter(name=row["name"]).exclude(pk=row["keep"])
        Hand.objects.filter(script__in=others).update(script_id=row["keep"])
        others.delete()


class Migration(migrations.Migration):
    dependencies = [("scribes", "0019_hand_display_order")]

    operations = [migrations.RunPython(merge_duplicate_scripts, migrations.RunPython.noop)]
