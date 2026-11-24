"""Print buy/resell opportunities from the collected data (same rules as the page).

  python -m collector.opportunities                 all categories, CSFloat resale
  python -m collector.opportunities --cat gl --fee 0.08 --min-sales 20 --top 10
  python -m collector.opportunities --json          machine-readable

Lists:
  listing  Skinport's cheapest listing below the 7-day sale median, net of the resale fee
  dip      7-day median well below the 90-day median while the item keeps selling
  wear     a better wear that sold cheaper than a worse one over 30 days
  backtest the buy-after-dip/rise rules from data/analysis/backtest.json

Doppler phases (several Skinport versions under one name) and pattern-priced
finishes (Case Hardened, Heat Treated) are left out: their medians mix prices.
Prices are converted with the Skinport-implied USD to BRL rate.
"""
import argparse
import json
import sys

from .common import DATA, read_json

PATTERN = {"Case Hardened", "Heat Treated"}
WEARS = ["FN", "MW", "FT", "WW", "BS"]


def load():
    catalog = read_json(DATA / "catalog.json")
    sp = read_json(DATA / "skinport" / "latest.json")
    if not catalog or not sp:
        sys.exit("opportunities: run the collectors first (catalog and Skinport data missing)")
    f = {n: i for i, n in enumerate(sp["fields"])}
    rows = {}
    for r in sp["rows"]:
        rows.setdefault(r[f["name"]], []).append(r)
    links = read_json(DATA / "skinport" / "links.json", {})
    fx = (read_json(DATA / "skinport" / "fx.json") or {}).get("usd_brl") or 1.0
    items = []
    for it in catalog["items"]:
        rs = rows.get(it["name"], [])
        if len(rs) != 1 or it["paint"] in PATTERN:
            continue
        r = rs[0]
        g = lambda k: r[f[k]]
        items.append({**it, "min": g("min_listing"), "listings": g("listings"),
                      "m7": g("med7d"), "m30": g("med30d"), "m90": g("med90d"),
                      "v7": g("vol7d"), "v30": g("vol30d"), "v90": g("vol90d"),
                      "link": links.get(it["name"])})
    return items, fx, sp["updated"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cat", choices=["all", "rf", "kn", "gl"], default="all")
    ap.add_argument("--fee", type=float, default=0.02, help="resale fee: 0.02 CSFloat, 0.08 Skinport")
    ap.add_argument("--min-sales", type=int, default=10, help="sales in the last 7 days")
    ap.add_argument("--min-price", type=float, default=2.0, help="USD")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    items, fx, updated = load()
    base = [i for i in items if (a.cat == "all" or i["cat"] == a.cat) and i["m7"] and i["m7"] / 100 >= a.min_price]

    listing = []
    for i in base:
        if i["min"] and i["v7"] >= a.min_sales:
            net = i["m7"] * (1 - a.fee) - i["min"]
            if net > 0:
                listing.append({"name": i["name"], "min_listing": i["min"] / 100, "median_7d": i["m7"] / 100,
                                "net_profit": net / 100, "net_pct": net / i["min"], "sales_7d": i["v7"],
                                "listings": i["listings"], "link": i["link"]})
    listing.sort(key=lambda x: -x["net_pct"])

    dip = [{"name": i["name"], "median_7d": i["m7"] / 100, "median_90d": i["m90"] / 100,
            "change": i["m7"] / i["m90"] - 1, "sales_7d": i["v7"], "sales_90d": i["v90"], "link": i["link"]}
           for i in base if i["m90"] and i["v7"] >= a.min_sales and i["v90"] >= 30 and i["m7"] / i["m90"] - 1 < -0.05]
    dip.sort(key=lambda x: x["change"])

    by = {}
    for i in base:
        if i["wear"] is not None and i["m30"] and i["v30"] >= 10:
            by.setdefault((i["weapon"], i["paint"]), []).append(i)
    wear = []
    for xs in by.values():
        for good in xs:
            for bad in xs:
                if good["wear"] < bad["wear"] and good["m30"] < bad["m30"] * 0.97:
                    wear.append({"skin": f"{good['weapon']} | {good['paint']}",
                                 "better": WEARS[good["wear"]], "better_median_30d": good["m30"] / 100,
                                 "worse": WEARS[bad["wear"]], "worse_median_30d": bad["m30"] / 100,
                                 "change": good["m30"] / bad["m30"] - 1, "link": good["link"]})
    wear.sort(key=lambda x: x["change"])

    bt = read_json(DATA / "analysis" / "backtest.json")
    out = {"data_updated": updated, "usd_brl": fx, "filters": vars(a),
           "listing": listing[: a.top], "dip": dip[: a.top], "wear": wear[: a.top], "backtest": bt}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    brl = lambda usd: f"R$ {usd * fx:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    print(f"Dados da Skinport de {updated} · câmbio {fx} · taxa de revenda {a.fee:.0%}\n")
    print(f"Anúncio abaixo da mediana de 7 dias ({len(listing)} itens com lucro líquido)")
    for x in listing[: a.top]:
        print(f"  {x['net_pct']:+6.1%}  {x['name'][:52]:52s} anúncio {brl(x['min_listing']):>13}  "
              f"mediana {brl(x['median_7d']):>13}  lucro {brl(x['net_profit']):>12}  v7 {x['sales_7d']}")
    print(f"\nAbaixo da mediana de 90 dias ({len(dip)} itens)")
    for x in dip[: a.top]:
        print(f"  {x['change']:+6.1%}  {x['name'][:52]:52s} 7d {brl(x['median_7d']):>13}  90d {brl(x['median_90d']):>13}  "
              f"v7/v90 {x['sales_7d']}/{x['sales_90d']}")
    print(f"\nDesgaste melhor mais barato ({len(wear)} casos)")
    for x in wear[: a.top]:
        print(f"  {x['change']:+6.1%}  {x['skin'][:44]:44s} {x['better']} {brl(x['better_median_30d'])} < "
              f"{x['worse']} {brl(x['worse_median_30d'])}")
    if bt:
        print(f"\nBacktest ({bt['items']} skins, mediana por operação, últimos 12 meses / todo o histórico)")
        for r in bt["rules"]:
            cells = []
            for h in r["holds"]:
                l12, al = h["last12m"], h["all"]
                cells.append(f"{h['weeks']}sem {l12['median']:+.1%}/{al['median']:+.1%}" if l12 and al else f"{h['weeks']}sem —")
            print(f"  {r['label'][:48]:48s} " + "  ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
