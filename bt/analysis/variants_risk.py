import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
st = pd.read_pickle("out/state.pkl")
F, fw, el, mkt, pen = st["F"], st["fw"], st["el"], st["mkt"], st["pen"]
avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)
I1, I5 = pct(F["instNet"] / avg), pct(F["inst5d"] / (avg * 5))
C, M = pct(F["foreignDays"] + 1.5 * F["trustDays"]), pct(-F["marginChg"].fillna(0) / avg)
M5 = pct(-F["marginAdd5"] / avg)
_, pm, pr = B.penalty(F)
pr50 = pd.DataFrame(np.where(F["ret20raw"] >= 50, 10, 0), index=pen.index, columns=pen.columns)
newbase = 10*I1 + 15*I5 + 25*C + 15*M5 + 12.5
V = {"A 現行": 25*I1 + 25*I5 + 10*C + 15*M + 12.5 - pen, "C 改權重": newbase - pen, "H 改權重不扣分": newbase,
     "H2 改權重＋只扣融資": newbase - pm, "H3 改權重＋只扣漲50%以上": newbase - pr50}
start = pd.Timestamp("2024-10-01")
rows = []
for name, sc in V.items():
    pk = B.top_picks(sc.where(el), F, mkt)
    R20, R5 = fw["o20"], fw["o5"]
    pk = pk.loc[start:] & ~fw["lockup"].loc[start:].fillna(False).astype(bool)
    vals = R20.loc[start:].where(pk).stack().dropna()
    d20 = E.picks_daily(pk, R20.loc[start:], el.loc[start:], mkt)
    d5 = E.picks_daily(pk, R5.loc[start:], el.loc[start:], mkt)
    ex5 = d5.groupby("date")["excess"].mean()
    rel = (1 + ex5.iloc[::5]).cumprod()
    rows.append({"方式": name, "20日超額%": d20["excess"].mean()*100, "5日超額%": d5["excess"].mean()*100,
                 "20日跌超過15%的比例%": (vals < -0.15).mean()*100, "20日漲超過30%的比例%": (vals > 0.3).mean()*100,
                 "個股20日報酬中位數%": vals.median()*100, "5日超額波動%": ex5.std()*100,
                 "相對大盤最大回落%": ((rel / rel.cummax()) - 1).min()*100, "持股平均20日漲幅%(選入時)": F["ret20raw"].loc[start:].where(pk).stack().mean()})
print(pd.DataFrame(rows).round(2).to_string(index=False))
