from io import StringIO

from django.core.management import call_command
import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory


@pytest.mark.django_db
def test_check_text_links_fails_with_truly_missing_graph():
    image = ItemImageFactory()
    ImageText.objects.create(
        item_image=image,
        content='<p><seg corresp="#gid-999999">Alpha</seg></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    out = StringIO()
    err = StringIO()
    with pytest.raises(SystemExit) as exc_info:
        call_command("check_text_links", stdout=out, stderr=err)

    assert exc_info.value.code == 1
    assert "missing: 1" in out.getvalue()
    assert "FAILED: 1 problem link(s) found" in err.getvalue()
