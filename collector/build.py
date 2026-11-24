"""Build site/index.html: the page template with all data embedded.

The data is packed small enough for one self-contained page:
  gzip( uint32 header length | header JSON | varint series per item )
  header: asof, fx, weapons [[name, cat]], paints [name],
          items [[weapon, paint, wear (5 = none), ref cents, ref volume, skinport|null]]
          skins {"weapon|paint": [image file|null, rarity, rarity colour]}
          skinport = [med7d, med30d, med90d, vol7d, vol30d, vol90d,
                      min listing, listings, med24h, vol24h] in USD cents
  series: n, then per point day, log-price code (ln(cents) * 200) and sales,
          the first point absolute and the rest as deltas (code zigzag).
Points are daily for the last `daily_days` days and weekly before that.
"""
import base64
import collections
import gzip
import json
import math
import struct
import sys

from .common import CONFIG, DATA, ROOT, read_json, slug

TEMPLATE = ROOT / "site" / "template.html"
OUT = ROOT / "site" / "index.html"


def varint(out: bytearray, x: int) -> None:
    x = int(x)
    while x >= 128:
        out.append((x & 127) | 128)
        x >>= 7
    out.append(x)


def series(rows, daily_days):
    if not rows:
        return []
    last = rows[-1][0]
    weekly = collections.OrderedDict()
    recent = []
    for day, cents, n in rows:
        if cents <= 0:
            continue
        if day > last - daily_days:
            recent.append((day, cents, n))
        else:
            w = weekly.setdefault(day // 7, [0, 0, 0])
            w[0] += cents * n
            w[1] += n
            w[2] = max(w[2], day)
    old = [(d, s / n, n) for s, n, d in weekly.values()]
    return [(d, round(math.log(c) * 200), n) for d, c, n in sorted(old) + recent]


def skinport_by_name():
    sp = read_json(DATA / "skinport" / "latest.json")
    if not sp:
        return {}, None
    f = {name: i for i, name in enumerate(sp["fields"])}
    groups = collections.defaultdict(list)
    for r in sp["rows"]:
        groups[r[f["name"]]].append(r)

    def wmed(rs, med, vol):
        pairs = [(r[f[med]], r[f[vol]]) for r in rs if r[f[med]] is not None]
        if not pairs:
            return None
        tot = sum(v for _, v in pairs)
        return round(sum(m * v for m, v in pairs) / tot) if tot else round(sum(m for m, _ in pairs) / len(pairs))

    out = {}
    for name, rs in groups.items():  # several rows = Doppler phases sharing a name
        mins = [r[f["min_listing"]] for r in rs if r[f["min_listing"]] is not None]
        out[name] = [wmed(rs, "med7d", "vol7d"), wmed(rs, "med30d", "vol30d"), wmed(rs, "med90d", "vol90d"),
                     sum(r[f["vol7d"]] for r in rs), sum(r[f["vol30d"]] for r in rs), sum(r[f["vol90d"]] for r in rs),
                     min(mins) if mins else None, sum(r[f["listings"]] or 0 for r in rs),
                     wmed(rs, "med24h", "vol24h"), sum(r[f["vol24h"]] for r in rs)]
    return out, sp["updated"]


def write_image_pack() -> None:
    """site/img/pack.json: every thumbnail as a data URL in one file, for hosts
    where the page may load its own files but not images from other sites."""
    img_dir = ROOT / "site" / "img"
    files = sorted(img_dir.glob("*.webp"))
    if not files:
        return
    pack = {f.name: "data:image/webp;base64," + base64.b64encode(f.read_bytes()).decode() for f in files}
    (img_dir / "pack.json").write_text(json.dumps(pack, separators=(",", ":")), encoding="utf-8")


def main() -> int:
    catalog = read_json(DATA / "catalog.json")
    if not catalog:
        print("build: no catalog", file=sys.stderr)
        return 1
    sp, sp_updated = skinport_by_name()
    fx = (read_json(DATA / "skinport" / "fx.json") or {}).get("usd_brl")
    meta = read_json(DATA / "meta.json", {})
    daily_days = CONFIG["history"]["daily_days"]

    weapons, widx, paints, pidx = [], {}, [], {}
    items, blob = [], bytearray()
    last_day, with_hist, with_sp = 0, 0, 0
    for it in catalog["items"]:
        if it["weapon"] not in widx:
            widx[it["weapon"]] = len(weapons)
            weapons.append([it["weapon"], it["cat"]])
        if it["paint"] not in pidx:
            pidx[it["paint"]] = len(paints)
            paints.append(it["paint"])
        s = sp.get(it["name"])
        if s and not any(s[:3]):
            s = None
        with_sp += s is not None
        items.append([widx[it["weapon"]], pidx[it["paint"]], 5 if it["wear"] is None else it["wear"],
                      it["ref_price"], it["ref_volume"], s])
        hist = read_json(DATA / "csfloat" / "history" / f"{slug(it['name'])}.json", {"rows": []})
        pts = series(hist["rows"], daily_days)
        with_hist += bool(pts)
        varint(blob, len(pts))
        prev_d = prev_c = 0
        for k, (d, c, n) in enumerate(pts):
            if k:
                varint(blob, d - prev_d)
                delta = c - prev_c
                varint(blob, 2 * delta if delta >= 0 else -2 * delta - 1)
            else:
                varint(blob, d)
                varint(blob, c)
            varint(blob, n)
            prev_d, prev_c = d, c
            last_day = max(last_day, d)

    asof = max(filter(None, [sp_updated, catalog.get("updated")]), default="")
    skins = {k: [m.get("img"), m.get("rarity"), m.get("color")] for k, m in meta.items()}
    header = json.dumps({"asof": asof, "fx": fx, "weapons": weapons, "paints": paints, "items": items,
                         "skins": skins},
                        ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    packed = gzip.compress(struct.pack("<I", len(header)) + header + bytes(blob), 9, mtime=0)
    page = TEMPLATE.read_text(encoding="utf-8").replace("__B64__", base64.b64encode(packed).decode())
    write_image_pack()
    OUT.write_text(page, encoding="utf-8")
    print(f"build: {len(items)} items, {with_hist} with CSFloat history, {with_sp} with Skinport stats, "
          f"{len(packed) // 1024} KB packed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
