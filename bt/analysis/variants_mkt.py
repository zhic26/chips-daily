import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B
pd.set_option("display.width", 220)
st = pd.read_pickle("out/state.pkl")
F, fw, el, mkt, pen = st["F"], st["fw"], st["el"], st["mkt"], st["pen"]
avg = F["avg5"]; dates = st["P_dates"]
pct = lambda X: B.pct_in_market(X, el, mkt)
I1, I5 = pct(F["instNet"] / avg), pct(F["inst5d"] / (avg * 5))
C, M = pct(F["foreignDays"] + 1.5 * F["trustDays"]), pct(-F["marginChg"].fillna(0) / avg)
M5 = pct(-F["marginAdd5"] / avg)
V = {"A 現行": 25*I1 + 25*I5 + 10*C + 15*M + 12.5 - pen,
     "C 改權重": 10*I1 + 15*I5 + 25*C + 15*M5 + 12.5 - pen,
     "G 現行不扣分": 25*I1 + 25*I5 + 10*C + 15*M + 12.5,
     "H 改權重不扣分": 10*I1 + 15*I5 + 25*C + 15*M5 + 12.5}
segs = (("前段", "2024-10-01", "2025-09-30"), ("後段", "2025-10-01", "2026-12-31"))
rows = []
for name, sc in V.items():
    pk = B.top_picks(sc.where(el), F, mkt)
    for h in (5, 20):
        d = E.picks_daily(pk, fw[f"o{h}"], el, mkt, lock=fw["lockup"])
        for seg, a, b in segs:
            g = d[(d["date"] >= a) & (d["date"] <= b)]
            for m in ("上市", "上櫃"):
                x = g[g["market"] == m]["excess"]
                rows.append({"方式": name, "h": f"{h}日", "段": seg, "市場": m, "v": f"{x.mean()*100:+.2f}"})
T = pd.DataFrame(rows)
print(T.pivot_table(index="方式", columns=["h", "市場", "段"], values="v", aggfunc="first").to_string())
