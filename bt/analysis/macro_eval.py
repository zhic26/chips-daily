"""美股（費半）能不能幫名單：1) 美股夜盤的漲跌是不是隔天開盤就反映完；2) 用選股當晚已知的費半狀態分組，看大盤與名單之後的表現。"""
import datetime as dt, json, sys
import numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B  # noqa: E402

st = pd.read_pickle("out/state.pkl")
F, fw, el, mkt, r = st["F"], st["fw"], st["el"], st["mkt"], st["r"]; dates = st["P_dates"]; avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)  # noqa: E731
M = "../bt-branch/bt/macro/"


def yseries(name):
    rows = json.load(open(M + f"yahoo_{name}.json"))
    s = pd.Series({dt.datetime.utcfromtimestamp(t).date(): c for t, c, o in rows if c is not None})
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


sox = yseries("SOX")
sret = sox.pct_change()
# 1) 美國第 T 天（台北 T 天晚上開盤）的費半漲跌 vs 台股 T+1 的跳空、盤中
elb = el.fillna(False).astype(bool)
gap = ((1 + r.shift(-1)) / (1 + fw["o1"]) - 1).where(elb).mean(axis=1)  # T+1 開盤相對 T 收盤
intra = fw["o1"].where(elb).mean(axis=1)                                   # T+1 開盤到收盤
us = sret.reindex(dates)  # 同一個日曆日的美股（台北當晚）
ok = us.notna() & gap.notna() & intra.notna() & (dates >= pd.Timestamp("2024-10-01"))
print(f"費半當晚漲跌 vs 台股隔天：跳空相關 {np.corrcoef(us[ok], gap[ok])[0, 1]:.2f}，開盤後到收盤相關 {np.corrcoef(us[ok], intra[ok])[0, 1]:.2f}（{ok.sum()} 天）")

# 2) 選股當晚（台北時間晚上）已知的費半狀態：用前一個美國交易日收盤
known = sox[sox.index < sox.index.max() + pd.Timedelta(days=1)]
state = pd.DataFrame({"ma50": sox / sox.rolling(50).mean() - 1, "r20": sox.pct_change(20),
                      "vol20": sret.rolling(20).std() * np.sqrt(252)})
asof = state.reindex(state.index.union(dates)).shift(1).ffill().reindex(dates)  # 嚴格早於台股日期
rv = pd.read_csv("../bt-branch/bt/extra2/revenue.csv", dtype={"code": str}).drop_duplicates(["ym", "code"])
rev = rv.pivot(index="ym", columns="code", values="rev").sort_index(); ly = rv.pivot(index="ym", columns="code", values="rev_ly").sort_index()
y3 = (rev.rolling(3).sum() / ly.rolling(3).sum() - 1).where(ly.rolling(3).sum() > 0) * 100
y3.index = pd.to_datetime(y3.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)
Y3 = y3.reindex(y3.index.union(dates)).ffill().reindex(dates).reindex(columns=F["close"].columns)
W0 = 10 * pct(F["instNet"] / avg) + 10 * pct(F["inst5d"] / (avg * 5)) + 30 * pct(F["foreignDays"] + 1.5 * F["trustDays"]) \
    + 15 * pct(-F["marginAdd5"].fillna(0) / avg) + 20 * pct(Y3).fillna(0.5)
inr = pd.Series(dates >= pd.Timestamp("2024-10-01"), index=dates)
pk = B.top_picks(W0.where(el), F, mkt).where(inr, axis=0).fillna(False).astype(bool)
elr = el.where(inr, axis=0).fillna(False).astype(bool)
groups = {"費半在 50 日均線之上": asof["ma50"] > 0, "費半在 50 日均線之下": asof["ma50"] <= 0,
          "費半波動低（後 1/3）": asof["vol20"] <= asof["vol20"].quantile(1 / 3),
          "費半波動高（前 1/3）": asof["vol20"] >= asof["vol20"].quantile(2 / 3)}
rows = []
for h in (5, 20):
    d = E.picks_daily(pk, fw[f"o{h}"], elr, mkt, lock=fw["lockup"]).groupby("date")[["pick", "univ", "excess"]].mean()
    for gname, mask in groups.items():
        g = d[mask.reindex(d.index).fillna(False)]
        rows.append({"持有": f"{h}日", "情況": gname, "天數": len(g), "大盤等權%": round(g["univ"].mean() * 100, 2),
                     "名單%": round(g["pick"].mean() * 100, 2), "超額%": round(g["excess"].mean() * 100, 2),
                     "超額>0天數%": round((g["excess"] > 0).mean() * 100)})
print(pd.DataFrame(rows).to_string(index=False))
