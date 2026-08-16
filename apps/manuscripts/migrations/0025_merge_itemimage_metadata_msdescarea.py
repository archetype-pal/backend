from django.db import migrations


class Migration(migrations.Migration):
    """Relink the two leaves into a single line.

    This feature's ItemImage upload-metadata fields branch off 0022, while
    main's line runs through MsDescArea to 0024. They touch different tables,
    so this is a pure ordering merge with no operations.
    """

    dependencies = [
        ("manuscripts", "0023_itemimage_checksum_sha256_itemimage_created_and_more"),
        ("manuscripts", "0024_remove_imagetext_content_dpt_legacy"),
    ]

    operations = []
