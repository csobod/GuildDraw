#!/usr/bin/env python3
"""Regenerate ``framedraft/resources/bpi_tints.json`` from BPI's online catalog.

BPI (Brain Power Inc.) publish a swatch image for every tint they sell — a
rendered lens disc in that dye, captioned with the tint name and part numbers.
Those discs are the only public, per-tint colour reference there is, so this
script walks the store's Tints categories, samples the middle of each disc, and
writes a name → approximate hex table that GuildDraw ships as the Lens Fill
colour reference.

The result is APPROXIMATE and unofficial: a JPEG of a rendered lens at BPI's
own display density is not a colorimetric measurement, and real tint depth
depends on dye time, lens material, and base curve. It is a starting point for
picking a plausible lens colour on screen, nothing more. GuildDraw is not
affiliated with BPI; tint names are theirs.

Run:  python scripts/scrape_bpi_tints.py [-o OUT.json] [--cache DIR]

Needs network access and PySide6 (for QImage JPEG decoding) — both dev-only;
the app itself just reads the shipped JSON.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT  = Path(__file__).resolve().parent.parent
_OUT   = _ROOT / "framedraft" / "resources" / "bpi_tints.json"
_STORE = "https://callbpi.com/golf/index.php"
_UA    = "GuildDrawTintScraper/1.0 (+https://github.com/gasm-cnc/GuildDraw)"

# Tint categories worth sampling, as (store path, family label). The packaging
# categories (Quarts, The Pill) are deliberately absent: they re-list colours
# that already appear above, and dedup keys on the swatch image anyway.
_CATEGORIES = [
    ("65_66",  "Standard"),
    ("65_89",  "Premium"),
    ("65_86",  "Therapeutic"),
    ("65_129", "UV Blocking"),
    ("65_83",  "IR"),
    ("65_98",  "Specialty"),
    ("65_91",  "EVA"),
    ("65_87",  "VDT"),
    ("65_81",  "Acrylic"),
    ("65_95",  "Polycarbonate"),
]

# One product tile: thumbnail URL, then the caption link's product name.
_TILE_RE = re.compile(
    r'<img src="(?P<img>[^"]+?-\d+x\d+\.jpg)"[^>]*/></a></div>.*?'
    r'<div class="caption">\s*<h4><a[^>]*>(?P<name>[^<]+)</a></h4>\s*'
    r'(?:<p>(?P<desc>[^<]*)</p>)?',
    re.S)

_REQUEST_PAUSE_S = 0.4   # be a polite guest on someone else's shop


def _fetch(url: str, cache: Path | None, binary: bool = False):
    key = re.sub(r"[^A-Za-z0-9._-]", "_", url)[-120:]
    blob = None
    if cache is not None:
        hit = cache / key
        if hit.exists():
            blob = hit.read_bytes()
    if blob is None:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:   # noqa: S310
            blob = resp.read()
        time.sleep(_REQUEST_PAUSE_S)
        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)
            (cache / key).write_bytes(blob)
    return blob if binary else blob.decode("utf-8", errors="replace")


def _clean_name(raw: str) -> str:
    """'BPI B&L Apricot - 3 oz bottle' -> 'B&L Apricot'."""
    name = html.unescape(raw).strip()
    name = re.sub(r"\s*[-–]\s*\d+\s*(oz|ounce|quart|gal)\w*\s*(bottle|jar)?\s*$", "",
                  name, flags=re.I)
    name = re.sub(r"\s*[-–]\s*(bottle|quart|pill|gallon)s?\s*$", "", name, flags=re.I)
    name = re.sub(r"^BPI\s*(®|&reg;)?\s*", "", name).strip()
    return re.sub(r"\s{2,}", " ", name)


def _swatch_key(img_url: str) -> str:
    """'…/catalog/tints2/aprc_b-228x228.jpg' -> 'aprc_b' — the colour identity.
    The same dye sold as a bottle, a quart and a pill reuses one swatch."""
    return re.sub(r"-\d+x\d+\.jpg$", "", img_url.rsplit("/", 1)[-1])


# A tint's swatch is a rendered lens disc; a few catalog entries (kits, dye
# concentrate, UV bottles) illustrate the *packaging* instead, and sampling
# those yields the colour of a bottle label rather than of any lens. Gate on the
# non-white blob being a centred, near-square disc of the expected size.
_DISC_ASPECT   = (0.90, 1.11)    # bbox width / height
_DISC_EXTENT   = (0.45, 0.78)    # bbox width as a fraction of image width
_DISC_OFFCENTRE = 0.10           # max centre drift, as a fraction of image width


def _disc_hex(blob: bytes) -> str | None:
    """Median colour of the middle of the rendered lens disc, or None if the
    image isn't a lens disc at all.

    The disc is drawn as a soft light-to-dark gradient on white, with the
    caption underneath. Find the non-white blob in the upper part of the image,
    then take the median over a band across its middle — the median shrugs off
    the JPEG ringing at the rim and the highlight at the top. Note the blob is
    only used to *locate* the disc: a pale tint is mostly above the white
    threshold, so its interior never registers, which is why the shape gate
    below tests the bounding box rather than how solidly it is filled.
    """
    from PySide6.QtGui import QImage
    img = QImage()
    if not img.loadFromData(blob) or img.isNull():
        return None
    w, h = img.width(), img.height()
    img = img.convertToFormat(QImage.Format.Format_RGB32)

    xs: list[int] = []
    ys: list[int] = []
    for y in range(0, int(h * 0.72)):
        for x in range(w):
            c = img.pixelColor(x, y)
            if c.red() < 241 or c.green() < 241 or c.blue() < 241:
                xs.append(x)
                ys.append(y)
    if len(xs) < 400:
        return None
    bw = max(xs) - min(xs) + 1
    bh = max(ys) - min(ys) + 1
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    r  = min(bw, bh) / 2.0
    if not (_DISC_ASPECT[0] <= bw / bh <= _DISC_ASPECT[1]):
        return None
    if not (_DISC_EXTENT[0] <= bw / w <= _DISC_EXTENT[1]):
        return None
    if abs(cx - w / 2.0) > _DISC_OFFCENTRE * w:
        return None
    if r < 10:
        return None

    reds: list[int] = []
    greens: list[int] = []
    blues: list[int] = []
    for y in range(int(cy - r * 0.18), int(cy + r * 0.18) + 1):
        for x in range(int(cx - r * 0.5), int(cx + r * 0.5) + 1):
            if 0 <= x < w and 0 <= y < h:
                c = img.pixelColor(x, y)
                reds.append(c.red())
                greens.append(c.green())
                blues.append(c.blue())
    if not reds:
        return None
    m = lambda v: int(statistics.median(v))    # noqa: E731
    return f"#{m(reds):02x}{m(greens):02x}{m(blues):02x}"


def scrape(cache: Path | None) -> list[dict]:
    seen: dict[str, dict] = {}
    for path, family in _CATEGORIES:
        page = 1
        while True:
            url = f"{_STORE}?route=product/category&path={path}&limit=100&page={page}"
            try:
                doc = _fetch(url, cache)
            except (urllib.error.URLError, TimeoutError) as exc:
                print(f"  ! {family} page {page}: {exc}", file=sys.stderr)
                break
            tiles = list(_TILE_RE.finditer(doc))
            if not tiles:
                break
            print(f"  {family} page {page}: {len(tiles)} products")
            for t in tiles:
                img_url = html.unescape(t.group("img"))
                key     = _swatch_key(img_url)
                if key in seen:
                    continue
                name = _clean_name(t.group("name"))
                if not name:
                    continue
                try:
                    hex_ = _disc_hex(_fetch(img_url, cache, binary=True))
                except (urllib.error.URLError, TimeoutError) as exc:
                    print(f"  ! {name}: {exc}", file=sys.stderr)
                    continue
                if hex_ is None:
                    print(f"  ~ skipped {name}: not a lens-disc swatch", file=sys.stderr)
                    continue
                desc = re.sub(r"\s*California residents.*$", "",
                              html.unescape(t.group("desc") or "")).strip(" .")
                seen[key] = {"name": name, "family": family,
                             "hex": hex_, "note": desc[:80]}
            if len(tiles) < 100:
                break
            page += 1
    return sorted(seen.values(), key=lambda e: (e["family"], e["name"].lower()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", type=Path, default=_OUT)
    ap.add_argument("--cache", type=Path, default=None,
                    help="reuse downloaded pages/images from this directory")
    args = ap.parse_args()

    from PySide6.QtGui import QGuiApplication
    QGuiApplication(["scrape_bpi_tints", "-platform", "offscreen"])

    print("Scraping callbpi.com tint catalog…")
    tints = scrape(args.cache)
    if not tints:
        print("No tints scraped — refusing to overwrite the shipped file.",
              file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {
            "source": "https://callbpi.com/golf/index.php?route=product/category&path=65",
            "scraped": time.strftime("%Y-%m-%d"),
            "disclaimer": (
                "Approximate on-screen colours sampled from BPI's own product "
                "swatch images. Unofficial and not colorimetric; GuildDraw is "
                "not affiliated with Brain Power Inc. Tint names are BPI's."
            ),
            "tints": tints,
        }, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(tints)} tints → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
