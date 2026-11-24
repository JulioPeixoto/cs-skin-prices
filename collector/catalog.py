"""Build data/catalog.json: every tracked skin with its market hash name.

Source: CSFloat's public schema, which lists every weapon, its paints, the
float range of each paint and CSFloat's reference price per wear.
Doppler phases share one market hash name, so they are merged into one item.
"""
import re
import sys

from .common import CONFIG, DATA, now_utc, read_json, session, write_json

SCHEMA_URL = "https://csfloat.com/api/v1/schema"
CATALOG = DATA / "catalog.json"
WEARS = ["Factory New", "Minimal Wear", "Field-Tested", "Well-Worn", "Battle-Scarred"]
WEAR_RANGES = [(0.0, 0.07), (0.07, 0.15), (0.15, 0.38), (0.38, 0.45), (0.45, 1.0)]
PHASE = re.compile(r"^(.*Doppler) \((.+)\)$")


def category_of(def_index: int):
    for key, cat in CONFIG["categories"].items():
        if def_index in cat.get("def_indexes", []):
            return key
        lo_hi = cat.get("def_range")
        if lo_hi and lo_hi[0] <= def_index <= lo_hi[1]:
            return key
    return None


def build(schema: dict) -> dict:
    merged = {}
    for def_str, weapon in schema["weapons"].items():
        cat = category_of(int(def_str))
        if not cat:
            continue
        star = "★ " if cat in ("kn", "gl") else ""
        for paint in weapon.get("paints", {}).values():
            prices = paint.get("normal_prices") or [0] * 5
            volumes = paint.get("normal_volume") or [0] * 5
            if paint.get("index") == 0:  # vanilla knife: no finish, no wear
                variants = [(f"{star}{weapon['name']}", "Vanilla", None, prices[0], volumes[0])]
            else:
                m = PHASE.match(paint["name"])
                paint_name = m.group(1) if m else paint["name"]
                variants = []
                for w, (lo, hi) in enumerate(WEAR_RANGES):
                    if paint["min"] < hi and paint["max"] > lo:
                        name = f"{star}{weapon['name']} | {paint_name} ({WEARS[w]})"
                        variants.append((name, paint_name, w, prices[w], volumes[w]))
            for name, paint_name, wear, price, volume in variants:
                it = merged.setdefault(name, {
                    "name": name, "cat": cat, "weapon": weapon["name"], "paint": paint_name,
                    "wear": wear, "_pv": 0, "_v": 0, "_min": None,
                })
                if price:
                    it["_pv"] += price * volume
                    it["_v"] += volume
                    it["_min"] = price if it["_min"] is None else min(it["_min"], price)
    items = []
    for it in merged.values():
        ref = round(it["_pv"] / it["_v"]) if it["_v"] else (it["_min"] or 0)
        items.append({k: v for k, v in it.items() if not k.startswith("_")} |
                     {"ref_price": ref, "ref_volume": it["_v"]})
    order = list(CONFIG["categories"])
    items.sort(key=lambda i: (order.index(i["cat"]), i["weapon"], i["paint"], -1 if i["wear"] is None else i["wear"]))
    return {"updated": now_utc().isoformat(timespec="seconds"), "source": SCHEMA_URL,
            "price_unit": "USD cents", "items": items}


def main() -> int:
    try:
        r = session().get(SCHEMA_URL, timeout=60)
        r.raise_for_status()
        schema = r.json()
    except Exception as exc:  # keep the previous catalog when CSFloat refuses
        print(f"catalog: could not fetch schema ({exc}); keeping current catalog", file=sys.stderr)
        return 0 if CATALOG.exists() else 1
    catalog = build(schema)
    old = read_json(CATALOG, {"items": []})
    write_json(CATALOG, catalog, pretty=True)
    print(f"catalog: {len(catalog['items'])} items (was {len(old['items'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
