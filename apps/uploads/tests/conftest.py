import pytest


@pytest.fixture(autouse=True)
def _temporary_upload_dirs(settings, tmp_path):
    """Sandbox the upload temp dir (MEDIA_ROOT is already swapped by the
    project-level autouse fixture)."""
    settings.UPLOADS_TMP_DIR = str(tmp_path / "uploads_tmp")


@pytest.fixture
def small_chunks(settings):
    """Tiny chunk size so multi-chunk flows are testable with a few bytes."""
    settings.UPLOADS_CHUNK_SIZE = 4
    return settings.UPLOADS_CHUNK_SIZE
