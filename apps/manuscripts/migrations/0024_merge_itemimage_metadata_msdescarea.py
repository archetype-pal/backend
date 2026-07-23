from django.db import migrations


class Migration(migrations.Migration):
    """Relink the two concurrent 0023 leaves into a single line.

    A rebase left two migrations branching off 0022: this feature's ItemImage
    upload-metadata fields and main's MsDescArea model. They touch different
    tables, so this is a pure ordering merge with no operations.
    """

    dependencies = [
        ("manuscripts", "0023_itemimage_checksum_sha256_itemimage_created_and_more"),
        ("manuscripts", "0023_msdescarea"),
    ]

    operations = []
