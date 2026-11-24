"""Collect CSFloat daily price history, a batch per run.

CSFloat's history endpoint returns one item per request and allows roughly
200 requests per hour, then answers 429 with a Retry-After of up to an hour.
Each run fetches at most `per_run` items, oldest first, and stops at the
first 429, so an hourly schedule walks the whole catalog in about 15 hours
and then keeps every item refreshed about once a day.

Writes data/csfloat/history/<slug>.json ({"name", "fetched", "rows"}) where
rows are [day since 1970-01-01, average sale price in USD cents, sales].
State lives in data/csfloat/state.json.
"""
import argparse
import datetime as dt
import sys
import time
import urllib.parse

from .common import CONFIG, DATA, now_utc, read_json, session, slug, write_json

URL = "https://csfloat.com/api/v1/history/{}/graph"
HIST = DATA / "csfloat" / "history"
STATE = DATA / "csfloat" / "state.json"


def fetch(s, name):
    r = s.get(URL.format(urllib.parse.quote(name, safe="")), timeout=30)
    if r.status_code == 429:
        return 429, int(r.headers.get("Retry-After", "3600") or 3600)
    if r.status_code != 200:
        return r.status_code, None
    return 200, r.json()


def to_rows(raw):
    out = []
    for x in raw:
        day = (dt.date.fromisoformat(x["day"][:10]) - dt.date(1970, 1, 1)).days
        out.append([day, round(x["avg_price"]), int(x.get("count") or 1)])
    out.sort()
    return out


def main() -> int:
    cfg = CONFIG["csfloat"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=cfg["per_run"])
    ap.add_argument("--delay", type=float, default=cfg["delay_seconds"])
    args = ap.parse_args()

    catalog = read_json(DATA / "catalog.json")
    if not catalog:
        print("csfloat: no catalog yet", file=sys.stderr)
        return 1
    state = read_json(STATE, {"fetched": {}, "blocked_until": 0})
    now = now_utc()
    if now.timestamp() < state.get("blocked_until", 0):
        wait = int(state["blocked_until"] - now.timestamp())
        print(f"csfloat: rate limited for {wait}s more; skipping run")
        return 0

    fresh_after = now.timestamp() - cfg["refresh_after_hours"] * 3600
    names = [i["name"] for i in catalog["items"]]
    due = [n for n in names if state["fetched"].get(n, 0) < fresh_after]
    due.sort(key=lambda n: state["fetched"].get(n, 0))  # never-fetched first

    s = session()
    done = empty = 0
    for name in due[: args.max]:
        status, payload = fetch(s, name)
        if status == 429:
            state["blocked_until"] = now_utc().timestamp() + payload
            print(f"csfloat: 429 after {done} items, retry in {payload}s")
            break
        if status == 200:
            rows = to_rows(payload)
            write_json(HIST / f"{slug(name)}.json",
                       {"name": name, "fetched": now_utc().date().isoformat(), "rows": rows})
            empty += not rows
        else:
            print(f"csfloat: {status} for {name}", file=sys.stderr)
        state["fetched"][name] = now_utc().timestamp()
        done += 1
        time.sleep(args.delay)

    keep = set(names)
    state["fetched"] = {n: t for n, t in state["fetched"].items() if n in keep}
    write_json(STATE, state, pretty=True)
    left = sum(1 for n in names if state["fetched"].get(n, 0) < fresh_after)
    print(f"csfloat: fetched {done} ({empty} without sales); {left} still due")
    return 0


if __name__ == "__main__":
    sys.exit(main())
