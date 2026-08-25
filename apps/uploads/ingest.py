"""Ingest pipeline: assembled upload → verified, SIPI-servable ItemImage.

Ordering is the safety property (issue #114 postmortem): the ItemImage row is
created only after a real SIPI tile has rendered from the converted file, so a
DB row can never point at an unservable path.

Search is NOT reindexed here. Like every other mutation in this codebase, the
index is refreshed manually from the search-engine backoffice page (which flags
out-of-sync segments) — auto-reindexing per upload would be an expensive
full-segment rebuild and inconsistent with the rest of the system.
"""

from collections.abc import Callable
import logging
from pathlib import Path
import shutil
import subprocess
from typing import Any
import urllib.request

from django.conf import settings
from django.db import transaction

from apps.manuscripts.models import ItemImage
from apps.uploads.models import UploadSession
from apps.uploads.services import assembled_path, media_root, session_tmp_dir

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

_STAGES = ("convert", "verify tile", "register")


class IngestError(Exception):
    pass


def verify_decodable(source: Path) -> None:
    """Reject non-image bytes before any conversion work.

    Uploads are validated by extension only — browsers report no MIME type for
    .jp2/.tif — and a .jp2 is copied straight through without vips. Without
    this check a mislabelled file is caught only by the SIPI tile test, which
    reports a bad upload as an image-server failure.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        Image.open(source).close()  # header read, no full decode
    except Image.DecompressionBombError:
        # Pillow only raises this AFTER parsing the header, so the file IS a
        # decodable image — just past Pillow's own DoS guard (2x 89M px, i.e.
        # ~13400 square). Real manuscript masters reach that, and vips streams
        # the conversion, so this must not fail a legitimate upload.
        pass
    except UnidentifiedImageError as exc:
        # Pillow's message is only "cannot identify image file <temp path>" —
        # no diagnostic value, and it would put the container's internal
        # storage layout in front of the editor.
        raise IngestError("File is not a decodable image.") from exc


def convert_to_jp2(source: Path, destination: Path) -> None:
    """Lossless JP2 via the vips CLI, Pillow fallback (mirrors scripts/convert_tif_to_jp2.py).

    Never leaves a truncated destination behind.
    """
    if shutil.which("vips"):
        try:
            subprocess.run(
                ["vips", "jp2ksave", str(source), str(destination), "--lossless"],
                check=True,
                capture_output=True,
                text=True,
            )
            if destination.exists() and destination.stat().st_size > 0:
                return
        except subprocess.CalledProcessError as exc:
            destination.unlink(missing_ok=True)
            logger.warning("vips jp2ksave failed for %s, trying Pillow: %s", source.name, exc.stderr)
    try:
        from PIL import Image

        with Image.open(source) as im:
            im.seek(0)
            im.load()
            im.convert("RGB").save(destination, format="JPEG2000", quality_mode="lossless")
    except Exception as exc:
        destination.unlink(missing_ok=True)
        # Pillow/vips messages name the temp file, so they go to the log; the
        # editor sees a reason, not the container's storage layout.
        logger.warning("JP2 conversion failed for %s: %s", source.name, exc, exc_info=True)
        raise IngestError(
            "Could not convert the image to JP2. The file may be corrupt or an unsupported variant."
        ) from exc
    if not destination.exists() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise IngestError("JP2 conversion produced no output.")


def smoke_test_tile(destination_path: str) -> None:
    """Request a real scaled tile from SIPI — info.json alone proves nothing
    (it 200s on files whose pixel data SIPI cannot decode)."""
    base = settings.UPLOADS_SIPI_BASE_URL.rstrip("/")
    identifier = destination_path.replace("/", "%2F")
    url = f"{base}/{identifier}/full/300,/0/default.jpg"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            if response.status != 200:
                logger.warning("SIPI tile check returned HTTP %s for %s", response.status, url)
                raise IngestError(f"The image server could not render a tile (HTTP {response.status}).")
    except IngestError:
        raise
    except Exception as exc:
        # `url` embeds the internal image-server address — log it, don't ship it.
        logger.warning("SIPI tile check failed for %s: %s", url, exc, exc_info=True)
        raise IngestError("The image server could not be reached to verify the converted image.") from exc


def ingest_session(session_id: str, progress: ProgressCallback | None = None) -> dict[str, Any]:
    def report(step: int, message: str) -> None:
        if progress is not None:
            progress(step, len(_STAGES), message)

    session = UploadSession.objects.select_related("item_part", "owner").get(pk=session_id)
    if session.status != UploadSession.Status.ASSEMBLED:
        raise IngestError(f"Session is '{session.status}', expected 'assembled'.")
    session.status = UploadSession.Status.PROCESSING
    session.save(update_fields=["status", "modified"])

    source = assembled_path(session)
    destination_abs = media_root() / session.destination_path
    is_jp2_source = source.suffix == ".jp2"

    try:
        verify_decodable(source)

        report(1, "Converting to lossless JP2…" if not is_jp2_source else "Placing JP2…")
        destination_abs.parent.mkdir(parents=True, exist_ok=True)
        if is_jp2_source:
            # Already SIPI-native: copy it through unchanged.
            shutil.copyfile(source, destination_abs)
        else:
            convert_to_jp2(source, destination_abs)
        destination_abs.chmod(0o644)

        report(2, "Verifying a real SIPI tile…")
        smoke_test_tile(session.destination_path)

        report(3, "Registering image…")
        with transaction.atomic():
            if ItemImage.objects.filter(image=session.destination_path).exists():
                raise IngestError(f"An ItemImage already references '{session.destination_path}'.")
            item_image = ItemImage(
                item_part=session.item_part,
                image=session.destination_path,
                locus=session.locus,
            )
            item_image._audit_actor = session.owner  # EditEvent attribution outside a request
            item_image.save()
            if session.tags:
                item_image.tags = session.tags
                item_image.save()
            session.item_image = item_image
            session.status = UploadSession.Status.COMPLETE
            session.error = ""
            session.save(update_fields=["item_image", "status", "error", "modified"])
        shutil.rmtree(session_tmp_dir(session), ignore_errors=True)
    except Exception as exc:
        # No row exists yet (the transaction rolled back or was never
        # reached), so remove the servable file — a path SIPI can serve with
        # no DB row is exactly the orphan-file class we must not create.
        destination_abs.unlink(missing_ok=True)
        session.status = UploadSession.Status.FAILED
        # `session.error` is serialized to the client. IngestError messages are
        # written for the editor and safe to show; anything else is unexpected
        # and its text can carry internal paths or a traceback.
        if isinstance(exc, IngestError):
            session.error = str(exc)[:2000]
        else:
            logger.exception("Unexpected failure ingesting upload session %s", session.pk)
            session.error = "Processing failed unexpectedly. An operator should check the worker logs."
        session.save(update_fields=["status", "error", "modified"])
        raise

    return {
        "session_id": str(session.pk),
        "item_image_id": item_image.pk,
        "destination": session.destination_path,
    }
