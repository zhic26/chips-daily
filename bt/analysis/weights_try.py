import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B
st = pd.read_pickle("out/state.pkl")
F, fw, el, mkt, pen = st["F"], st["fw"], st["el"], st["mkt"], st["pen"]
avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)
I1, I5 = pct(F["instNet"] / avg), pct(F["inst5d"] / (avg * 5))
C, M = pct(F["foreignDays"] + 1.5 * F["trustDays"]), pct(-F["marginChg"].fillna(0) / avg)
M5 = pct(-F["marginAdd5"].fillna(0) / avg)
W = {"現行 25/25/10/15(今日融資)/25 扣分": 25*I1 + 25*I5 + 10*C + 15*M - pen,
     "H 10/15/25/15/25 不扣": 10*I1 + 15*I5 + 25*C + 15*M5,
     "W1 10/15/30/20/25": 10*I1 + 15*I5 + 30*C + 20*M5,
     "W2 10/20/30/15/25": 10*I1 + 20*I5 + 30*C + 15*M5,
     "W3 10/15/35/15/25": 10*I1 + 15*I5 + 35*C + 15*M5,
     "W4 11/17/28/17/27": 11*I1 + 17*I5 + 28*C + 17*M5}
segs = (("前段", "2024-10-01", "2025-09-30"), ("後段", "2025-10-01", "2026-12-31"))
rows = []
for name, sc in W.items():
    pk = B.top_picks(sc.where(el), F, mkt)
    row = {"權重(今日/5日/連買/融資/大戶)": name}
    for h in (5, 20):
        d = E.picks_daily(pk, fw[f"o{h}"], el, mkt, lock=fw["lockup"])
        for seg, a, b in segs:
            g = d[(d["date"] >= a) & (d["date"] <= b)].groupby("date")["excess"].mean()
            row[f"{h}日{seg}"] = round(g.mean() * 100, 2)
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))
