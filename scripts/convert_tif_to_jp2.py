#!/usr/bin/env python3
"""Convert legacy TIFF manuscript images to lossless JPEG-2000 for the Archetype 3 IIIF server.

Why this exists (issue archetype-pal/backend#114)
--------------------------------------------------
SIPI serves each ItemImage by a literal file lookup: the relative path stored in
`manuscripts_itemimage.image` (with '/' -> '%2F') must exist on disk under MEDIA_ROOT.
The database rows already point to `.jp2`, but the legacy files are TIFF. Worse, the
vast majority of those TIFFs are JPEG-compressed-in-TIFF (compression type 7), which
SIPI v5.0.1 / libtiff cannot decode: `info.json` returns 200 (header-only read) but
tile requests fail with 500. The fix is to store every image as `.jp2`, which SIPI
serves natively.

What this script does
---------------------
Walks a media root and, for every `*.tif`/`*.tiff`, writes a lossless `*.jp2` sibling:
  1. primary path: libvips `jp2ksave --lossless` (fast, native, multi-resolution);
  2. fallback: Pillow, for the handful of malformed files vips rejects
     (JPEG-in-TIFF that also declare an alpha channel — an invalid combination
     vips and SIPI both refuse, but PIL can decode the first page).
It is collision-safe (never overwrites an existing `.jp2`) and NON-destructive: the
`.tif` files are kept. Deleting them is a separate, opt-in step to run only after
verifying the jp2s render through SIPI (see the issue writeup).

PREREQUISITE — the source .tif files must already be present under the media root at
their DB-relative paths. This script converts what is on disk; it does not fetch
anything. On a server whose storage/media has no images yet, copy the source images
there first, THEN run this.

Usage
-----
    python3 convert_tif_to_jp2.py [MEDIA_ROOT]      # default: ./storage/media

Dependencies: libvips (`apt-get install libvips-tools`) and Pillow
(`apt-get install python3-pil`, or `pip install pillow`).

After it finishes: smoke-test a few jp2 through SIPI with a real TILE request
(`/full/300,/0/default.jpg`), not just `info.json` — then reindex the search engine
so the baked IIIF URLs update:
    just reindex        # infrastructure/ stack (dev stack: just sync-all-search-indexes)
"""

import argparse
import os
import shutil
import subprocess
import sys

try:
    from PIL import Image
except ImportError:
    Image = None

TIF_EXTENSIONS = (".tif", ".tiff")


def convert_with_vips(src: str, dst: str) -> bool:
    try:
        subprocess.run(
            ["vips", "jp2ksave", src, dst, "--lossless"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        if os.path.exists(dst):
            os.remove(dst)  # never leave a truncated jp2 behind
        return False
    return os.path.exists(dst) and os.path.getsize(dst) > 0


def convert_with_pillow(src: str, dst: str) -> bool:
    """Fallback for JPEG-in-TIFF-with-alpha that vips rejects; decodes the first page."""
    if Image is None:
        return False
    try:
        im = Image.open(src)
        im.seek(0)
        im.load()
        im.convert("RGB").save(dst, format="JPEG2000", quality_mode="lossless")
    except Exception:
        if os.path.exists(dst):
            os.remove(dst)
        return False
    return os.path.exists(dst) and os.path.getsize(dst) > 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert *.tif to lossless *.jp2 for the IIIF server.")
    parser.add_argument(
        "media_root", nargs="?", default="storage/media", help="Media root to walk (default: storage/media)"
    )
    args = parser.parse_args()

    if shutil.which("vips") is None:
        print("ERROR: `vips` not found — install libvips (apt-get install libvips-tools).", file=sys.stderr)
        return 2

    root = os.path.abspath(args.media_root)
    if not os.path.isdir(root):
        print(f"ERROR: media root not found: {root}", file=sys.stderr)
        return 2

    tifs = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith(TIF_EXTENSIONS):
                tifs.append(os.path.join(dirpath, name))

    if not tifs:
        print(f"No .tif files found under {root}. If images are missing here, copy the source files in first.")
        return 0

    print(f"Found {len(tifs)} TIFF file(s) under {root}\n")

    ok = recovered = skipped = failed = 0
    failures = []
    for src in sorted(tifs):
        rel = os.path.relpath(src, root)
        dst = os.path.splitext(src)[0] + ".jp2"
        if os.path.exists(dst):
            skipped += 1
            continue
        if convert_with_vips(src, dst):
            os.chmod(dst, 0o644)
            ok += 1
            print(f"OK: {rel}", flush=True)
        elif convert_with_pillow(src, dst):
            os.chmod(dst, 0o644)
            recovered += 1
            print(f"RECOVERED (pillow): {rel}", flush=True)
        else:
            failed += 1
            failures.append(rel)
            print(f"FAILED: {rel}", flush=True)

    print("\n--- summary ---")
    print(f"  converted (vips):     {ok}")
    print(f"  recovered (pillow):   {recovered}")
    print(f"  skipped (jp2 exists): {skipped}")
    print(f"  failed:               {failed}")
    if failures:
        print("  failed files:")
        for f in failures:
            print(f"    {f}")
        if Image is None:
            print(
                "  NOTE: Pillow is not installed — install it (apt-get install python3-pil"
                " or pip install pillow) to recover malformed TIFFs, then re-run."
            )
    print(
        "\nNext: smoke-test a few jp2 through SIPI with a TILE request "
        "(/full/300,/0/default.jpg — info.json alone can lie), then reindex."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
