"""Backtest simple buy-and-hold rules on the CSFloat price history.

Every item's daily averages become weekly medians (week = day // 7). For
each week with enough past data the price is compared with the median of
the previous 13 weeks (about 90 days). A rule decides whether to "buy" at
that week's price; the trade is closed `hold` weeks later at that week's
price minus the seller fee. Holds start at 2 weeks because CS2's Trade
Protection keeps a received item untradeable for 7 days.

Writes data/analysis/backtest.json with, per rule and hold, the number of
trades, median and mean return, share of winning trades, and the same
split by category and for the last 12 months only.

Caveat: CSFloat's daily average mixes ordinary sales with premium ones
(stickers, low floats). Weekly medians soften that, but results are an
estimate, not a promise.
"""
import statistics
import sys

from .common import DATA, read_json, slug, write_json

LOOKBACK = 13
MIN_PAST = 8
HOLDS = [2, 4, 8, 12]
MIN_SALES = 10  # weekly sales needed at entry and exit, so thin weeks don't fake a bounce
FEE = 0.02  # CSFloat seller fee
RULES = [
    ("any", "Comprar em qualquer semana (referência)", lambda chg: True),
    ("dip15", "Comprar após queda de 15%+ vs média de 90 dias", lambda chg: chg <= -0.15),
    ("dip25", "Comprar após queda de 25%+ vs média de 90 dias", lambda chg: chg <= -0.25),
    ("rise15", "Comprar após alta de 15%+ vs média de 90 dias", lambda chg: chg >= 0.15),
]


def weekly(rows):
    """{week: (median of the daily averages, sales that week)}"""
    weeks = {}
    for day, cents, n in rows:
        if cents > 0:
            weeks.setdefault(day // 7, []).append((cents, n))
    return {w: (statistics.median(c for c, _ in v), sum(n for _, n in v)) for w, v in weeks.items()}


def summarize(rets):
    if not rets:
        return None
    clipped = [max(-0.9, min(3.0, r)) for r in rets]  # one freak sale can't drive the mean
    return {"n": len(rets), "median": round(statistics.median(rets), 4),
            "mean": round(statistics.fmean(clipped), 4),
            "win": round(sum(r > 0 for r in rets) / len(rets), 4)}


def main() -> int:
    catalog = read_json(DATA / "catalog.json")
    if not catalog:
        print("backtest: no catalog", file=sys.stderr)
        return 1
    trades = {}  # (rule, hold) -> list of (cat, recent, ret)
    last_week, items = 0, 0
    series = []
    for it in catalog["items"]:
        h = read_json(DATA / "csfloat" / "history" / f"{slug(it['name'])}.json")
        if not h or not h["rows"]:
            continue
        w = weekly(h["rows"])
        if len(w) < MIN_PAST + 2:
            continue
        series.append((it["cat"], w))
        last_week = max(last_week, max(w))
        items += 1
    recent_from = last_week - 52
    for cat, w in series:
        for t in sorted(w):
            if w[t][1] < MIN_SALES:
                continue
            past = [w[x][0] for x in range(t - LOOKBACK, t) if x in w]
            if len(past) < MIN_PAST:
                continue
            chg = w[t][0] / statistics.median(past) - 1
            for key, _label, rule in RULES:
                if not rule(chg):
                    continue
                for hold in HOLDS:
                    exit_w = next((x for x in (t + hold, t + hold + 1, t + hold - 1)
                                   if x in w and x > t and w[x][1] >= MIN_SALES), None)
                    if exit_w is None:
                        continue
                    ret = w[exit_w][0] * (1 - FEE) / w[t][0] - 1
                    trades.setdefault((key, hold), []).append((cat, t >= recent_from, ret))

    out = {"items": items, "last_week_start_day": last_week * 7, "fee": FEE, "min_weekly_sales": MIN_SALES,
           "lookback_weeks": LOOKBACK, "rules": []}
    for key, label, _ in RULES:
        rule = {"key": key, "label": label, "holds": []}
        for hold in HOLDS:
            tr = trades.get((key, hold), [])
            rule["holds"].append({
                "weeks": hold,
                "all": summarize([r for _, _, r in tr]),
                "last12m": summarize([r for _, rec, r in tr if rec]),
                "by_cat": {c: summarize([r for cc, _, r in tr if cc == c]) for c in ("rf", "kn", "gl")},
            })
        out["rules"].append(rule)
    write_json(DATA / "analysis" / "backtest.json", out, pretty=True)
    any4 = next(h for h in out["rules"][0]["holds"] if h["weeks"] == 4)["all"]
    print(f"backtest: {items} items; any-week 4w median {any4 and any4['median']:+.3f}" if any4 else
          f"backtest: {items} items; not enough history yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
