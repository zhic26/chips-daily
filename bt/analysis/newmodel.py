"""新規則（10/15/30/20/25、融資看 5 日、不扣分）的回測摘要，給網站說明用。"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B
st = pd.read_pickle("out/state.pkl")
reg = pd.read_csv("out/regime.csv", index_col=0, parse_dates=True)
F, fw, el, mkt, pen = st["F"], st["fw"], st["el"], st["mkt"], st["pen"]
avg = F["avg5"]; dates = st["P_dates"]; start = pd.Timestamp("2024-10-01")
pct = lambda X: B.pct_in_market(X, el, mkt)
sc = (10 * pct(F["instNet"] / avg) + 15 * pct(F["inst5d"] / (avg * 5)) + 30 * pct(F["foreignDays"] + 1.5 * F["trustDays"])
      + 20 * pct(-F["marginAdd5"].fillna(0) / avg) + 12.5)
old = 25 * pct(F["instNet"] / avg) + 25 * pct(F["inst5d"] / (avg * 5)) + 10 * pct(F["foreignDays"] + 1.5 * F["trustDays"]) + 15 * pct(-F["marginChg"].fillna(0) / avg) + 12.5 - pen
inr = pd.Series(dates >= start, index=dates)
for lab, s in (("舊規則", old), ("新規則", sc)):
    pk = B.top_picks(s.where(el), F, mkt).where(inr, axis=0).fillna(False).astype(bool)
    elr = el.where(inr, axis=0).fillna(False).astype(bool)
    print(f"\n===== {lab} =====")
    for h in (5, 20):
        d = E.picks_daily(pk, fw[f"o{h}"], elr, mkt, lock=fw["lockup"])
        print(E.summarize(d, h, f"{h}日")[["組合", "市場", "天數", "選股平均%", "大盤等權%", "超額%", "超額為正的天數%", "個股贏大盤%", "t值"]].round(2).to_string(index=False))
        for m in ("上市", "上櫃"):
            g = d[d["market"] == m].set_index("date").join(reg)
            g["寬度"] = pd.cut(g[f"站上季線%_{m}"], [0, 35, 50, 100], labels=["<35%", "35~50%", ">50%"])
            t = g.groupby("寬度", observed=True).agg(超額=("excess", "mean"), 天數=("excess", "size"), 正=("excess", lambda x: (x > 0).mean()))
            print(f"  {h}日 {m} 依寬度：", "；".join(f"{i} {r['超額']*100:+.2f}%（{int(r['天數'])}天，{r['正']*100:.0f}%天贏）" for i, r in t.iterrows()))
