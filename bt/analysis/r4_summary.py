import sys, os, json, numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B
st = pd.read_pickle("out/state.pkl"); reg = pd.read_csv("out/regime.csv", index_col=0, parse_dates=True)
F, fw, el, mkt = st["F"], st["fw"], st["el"], st["mkt"]; dates = st["P_dates"]; avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)
rv = pd.read_csv("../bt-branch/bt/extra2/revenue.csv", dtype={"code": str}).drop_duplicates(["ym", "code"])
rev = rv.pivot(index="ym", columns="code", values="rev").sort_index(); ly = rv.pivot(index="ym", columns="code", values="rev_ly").sort_index()
y3 = (rev.rolling(3).sum() / ly.rolling(3).sum() - 1).where(ly.rolling(3).sum() > 0) * 100
y3.index = pd.to_datetime(y3.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)
Y3 = y3.reindex(y3.index.union(dates)).ffill().reindex(dates).reindex(columns=F["close"].columns)
sc = 10 * pct(F["instNet"] / avg) + 10 * pct(F["inst5d"] / (avg * 5)) + 30 * pct(F["foreignDays"] + 1.5 * F["trustDays"]) \
     + 15 * pct(-F["marginAdd5"].fillna(0) / avg) + 20 * pct(Y3).fillna(0.5)
inr = pd.Series(dates >= pd.Timestamp("2024-10-01"), index=dates)
pk = B.top_picks(sc.where(el), F, mkt).where(inr, axis=0).fillna(False).astype(bool)
elr = el.where(inr, axis=0).fillna(False).astype(bool)
out = {"overall": {}, "by_breadth": {"上市": {}, "上櫃": {}}}
for h in (5, 20):
    d = E.picks_daily(pk, fw[f"o{h}"], elr, mkt, lock=fw["lockup"])
    for m in ("上市", "上櫃"):
        g = d[d["market"] == m].set_index("date").join(reg)
        out["overall"].setdefault(m, {})[f"d{h}"] = round(g["excess"].mean() * 100, 2)
        b = pd.cut(g[f"站上季線%_{m}"], [0, 35, 50, 100], labels=[0, 1, 2])
        out["by_breadth"][m][f"d{h}"] = [round(g["excess"][b == k].mean() * 100, 2) for k in (0, 1, 2)]
    out.setdefault("days", int(d["date"].nunique()))
    s = E.summarize(d, h)
    print(h, "日 合計超額", round(s[s["市場"] == "合計"]["超額%"].iloc[0], 2), "t", round(s[s["市場"] == "合計"]["t值"].iloc[0], 2))
print(json.dumps(out, ensure_ascii=False))
