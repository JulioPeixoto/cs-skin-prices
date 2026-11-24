"""Collect Skinport's sales statistics for every CS2 item (one request).

Writes:
  data/skinport/latest.json       stats for every item, overwritten each run
  data/skinport/daily/DATE.json.gz one small snapshot per day, so a real daily
                                   series builds up over time
  data/skinport/fx.json           USD to BRL rate implied by Skinport's prices
  data/skinport/links.json        Skinport item page of every tracked skin

API: https://docs.skinport.com (no key; 8 requests per 5 minutes; responses
are cached for 5 minutes; Accept-Encoding: br is required).
"""
import statistics
import sys

from .common import DATA, now_utc, read_json, session, write_json

BASE = "https://api.skinport.com/v1"
WINDOWS = ["last_24_hours", "last_7_days", "last_30_days", "last_90_days"]
FIELDS = ["name", "version",
          "med24h", "med7d", "med30d", "med90d",
          "avg24h", "avg7d", "avg30d", "avg90d",
          "vol24h", "vol7d", "vol30d", "vol90d",
          "min_listing", "listings"]


def get(s, path, **params):
    r = s.get(f"{BASE}/{path}", params={"app_id": 730, **params},
              headers={"Accept-Encoding": "br"}, timeout=120)
    r.raise_for_status()
    return r.json()


def cents(x):
    return None if x is None else round(x * 100)


def main() -> int:
    s = session()
    try:
        history = get(s, "sales/history", currency="USD")
        items_usd = get(s, "items", currency="USD")
        items_brl = get(s, "items", currency="BRL")
    except Exception as exc:
        print(f"skinport: request failed ({exc})", file=sys.stderr)
        return 1

    listings = {(i["market_hash_name"], i.get("version")): i for i in items_usd}
    rows = []
    for h in history:
        key = (h["market_hash_name"], h.get("version"))
        lst = listings.get(key, {})
        rows.append([h["market_hash_name"], h.get("version")]
                    + [cents(h[w]["median"]) for w in WINDOWS]
                    + [cents(h[w]["avg"]) for w in WINDOWS]
                    + [h[w]["volume"] for w in WINDOWS]
                    + [cents(lst.get("min_price")), lst.get("quantity", 0)])
    rows.sort(key=lambda r: (r[0], r[1] or ""))

    brl = {(i["market_hash_name"], i.get("version")): i.get("suggested_price") for i in items_brl}
    ratios = [brl[k] / v["suggested_price"] for k, v in listings.items()
              if v.get("suggested_price") and brl.get(k) and v["suggested_price"] >= 1]
    fx = round(statistics.median(ratios), 4) if ratios else None

    stamp = now_utc()
    write_json(DATA / "skinport" / "latest.json",
               {"updated": stamp.isoformat(timespec="seconds"), "currency": "USD cents",
                "fields": FIELDS, "rows": rows})
    write_json(DATA / "skinport" / "daily" / f"{stamp.date().isoformat()}.json.gz",
               {"date": stamp.date().isoformat(), "currency": "USD cents",
                "fields": ["name", "version", "med24h", "vol24h", "min_listing"],
                "rows": [[r[0], r[1], r[2], r[10], r[14]] for r in rows if r[10] or r[14]]})
    tracked = {i["name"] for i in (read_json(DATA / "catalog.json") or {"items": []})["items"]}
    links = {k[0]: v["item_page"] for k, v in listings.items()
             if k[0] in tracked and v.get("item_page") and k[1] is None}
    write_json(DATA / "skinport" / "links.json", dict(sorted(links.items())), pretty=True)
    if fx:
        write_json(DATA / "skinport" / "fx.json",
                   {"updated": stamp.isoformat(timespec="seconds"), "usd_brl": fx,
                    "method": "median BRL/USD ratio of Skinport suggested prices"}, pretty=True)
    print(f"skinport: {len(rows)} items, usd_brl={fx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
