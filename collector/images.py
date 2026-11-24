"""Skin images and rarity from the open CSGO-API dataset.

Source: https://github.com/ByMykel/CSGO-API (public JSON with every skin's
Steam image URL, rarity with its colour and float range).

Writes data/meta.json keyed by "weapon|paint" and downloads one thumbnail
per finish into site/img/ (only the ones still missing). Doppler phases
share one market name, so the "Phase 2" image (or the first) stands for all.

  python -m collector.images              metadata + missing images
  python -m collector.images --no-images  metadata only
"""
import argparse
import io
import sys

from .common import DATA, ROOT, read_json, session, slug, write_json

SKINS_URL = "https://raw.githubusercontent.com/ByMykel/CSGO-API/main/public/api/en/skins.json"
IMG_DIR = ROOT / "site" / "img"
THUMB_W = 192


def pick(cands):
    def rank(s):
        return (bool(s.get("legacy_model")), s.get("phase") not in (None, "Phase 2"))
    return sorted(cands, key=rank)[0] if cands else None


def to_webp(raw: bytes) -> bytes:
    from PIL import Image  # imported here so --no-images works without Pillow
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    im.thumbnail((THUMB_W, THUMB_W))
    out = io.BytesIO()
    im.save(out, "WEBP", quality=78, method=6)
    return out.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args()

    catalog = read_json(DATA / "catalog.json")
    if not catalog:
        print("images: no catalog", file=sys.stderr)
        return 1
    s = session()
    try:
        r = s.get(SKINS_URL, timeout=120)
        r.raise_for_status()
        skins = r.json()
    except Exception as exc:
        print(f"images: could not fetch skins.json ({exc}); keeping current meta", file=sys.stderr)
        return 0
    by_name = {}
    for sk in skins:
        by_name.setdefault(sk["name"], []).append(sk)

    old = read_json(DATA / "meta.json", {})
    meta, missing, got, failed = {}, 0, 0, 0
    for it in {(i["weapon"], i["paint"], i["cat"]) for i in catalog["items"]}:
        weapon, paint, cat = it
        star = "★ " if cat in ("kn", "gl") else ""
        name = f"{star}{weapon}" if paint == "Vanilla" else f"{star}{weapon} | {paint}"
        sk = pick(by_name.get(name, []))
        key = f"{weapon}|{paint}"
        if not sk:
            missing += 1
            if key in old:
                meta[key] = old[key]
            continue
        rarity = sk.get("rarity") or {}
        file = f"{slug(key)}.webp"
        entry = {"name": name, "rarity": rarity.get("name"), "color": rarity.get("color"),
                 "min_float": sk.get("min_float"), "max_float": sk.get("max_float"),
                 "image_url": sk.get("image"), "img": None}
        path = IMG_DIR / file
        if path.exists():
            entry["img"] = file
        elif not args.no_images and sk.get("image"):
            try:
                ir = s.get(sk["image"], timeout=30)
                ir.raise_for_status()
                IMG_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(to_webp(ir.content))
                entry["img"] = file
                got += 1
            except Exception as exc:
                failed += 1
                print(f"images: {name}: {exc}", file=sys.stderr)
        meta[key] = entry
    write_json(DATA / "meta.json", dict(sorted(meta.items())), pretty=True)
    have = sum(1 for m in meta.values() if m.get("img"))
    print(f"images: {len(meta)} finishes, {have} with image ({got} new, {failed} failed), {missing} not in CSGO-API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
