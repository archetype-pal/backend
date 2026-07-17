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
from apps.uploads.services import archive_folder, assembled_path, media_root, originals_root, session_tmp_dir

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

_STAGES = ("inspect", "convert", "verify tile", "archive original", "register")


class IngestError(Exception):
    pass


def extract_metadata(source: Path) -> dict[str, Any]:
    """Dimensions, format and EXIF via Pillow header reads (no full decode)."""
    from PIL import ExifTags, Image, UnidentifiedImageError

    try:
        with Image.open(source) as im:
            width, height = im.size
            source_format = (im.format or "").lower()
            exif: dict[str, str] = {}
            for tag_id, value in im.getexif().items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                text = str(value)
                if len(text) <= 200:  # skip maker-note blobs etc.
                    exif[name] = text
    except UnidentifiedImageError as exc:
        raise IngestError(f"File is not a decodable image: {exc}") from exc
    return {"width": width, "height": height, "source_format": source_format, "exif": exif or None}


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
        raise IngestError(f"JP2 conversion failed: {exc}") from exc
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
                raise IngestError(f"SIPI tile check returned HTTP {response.status} for {url}")
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError(f"SIPI tile check failed for {url}: {exc}") from exc


def _archive_original(session: UploadSession, source: Path) -> str:
    """Move the untouched upload into the originals archive; return its
    archive-relative path."""
    folder = archive_folder(session.item_part_id, session.subfolder)
    relative = f"{folder}/{session.original_filename}"
    target = originals_root() / relative
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise IngestError(f"Original archive collision at '{relative}'.")
        shutil.move(str(source), target)
        target.chmod(0o644)
    except PermissionError as exc:
        # Deployment problem, not a data problem — say so instead of a bare
        # "[Errno 13] Permission denied" (the originals tree must be writable
        # by the backend container user).
        raise IngestError(
            f"Originals archive is not writable by the service user ({exc}). "
            f"An operator must fix ownership/permissions on '{originals_root()}'."
        ) from exc
    return relative


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
        report(1, "Inspecting image…")
        metadata = extract_metadata(source)

        report(2, "Converting to lossless JP2…" if not is_jp2_source else "Placing JP2…")
        destination_abs.parent.mkdir(parents=True, exist_ok=True)
        if is_jp2_source:
            # Already SIPI-native: the served copy IS the original bytes, so
            # nothing separate is archived (original_path stays empty).
            shutil.copyfile(source, destination_abs)
        else:
            convert_to_jp2(source, destination_abs)
        destination_abs.chmod(0o644)

        report(3, "Verifying a real SIPI tile…")
        smoke_test_tile(session.destination_path)

        report(4, "Archiving original…")
        original_path = "" if is_jp2_source else _archive_original(session, source)

        report(5, "Registering image…")
        with transaction.atomic():
            if ItemImage.objects.filter(image=session.destination_path).exists():
                raise IngestError(f"An ItemImage already references '{session.destination_path}'.")
            item_image = ItemImage(
                item_part=session.item_part,
                image=session.destination_path,
                locus=session.locus,
                width=metadata["width"],
                height=metadata["height"],
                source_format=metadata["source_format"],
                size_bytes=session.declared_size,
                checksum_sha256=session.computed_sha256,
                original_path=original_path,
                exif=metadata["exif"],
                uploaded_by=session.owner,
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
        session.error = str(exc)[:2000]
        session.save(update_fields=["status", "error", "modified"])
        raise

    return {
        "session_id": str(session.pk),
        "item_image_id": item_image.pk,
        "destination": session.destination_path,
        "original_path": original_path,
    }
