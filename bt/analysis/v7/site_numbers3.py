"""十二年的名單 5／20 日超額，算法跟網站 2 年版（bt_eval.picks_daily）一樣：
選股日 T 的名單、隔天開盤買、第 T+h 天收盤（還原權息），隔天一開盤就鎖漲停的不算；
對照組是 T 那天同市場合格股各自用同樣方式買的平均（不扣成本）。每天先平均，再對天數平均。
另外依名單那天的站上季線比例分組（跟網站「盤勢提醒」同定義）。結果存 out/site_numbers3.json"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())

Cv = C.values
ma = C.rolling(60, min_periods=55).mean()
valid = C.notna() & ma.notna()
above = (C > ma) & valid
BR = {}
for m in ("上市", "上櫃"):
    c = mkt.index[mkt == m]
    tot = valid[c].sum(axis=1)
    BR[m] = (above[c].sum(axis=1) / tot * 100).where(tot >= 50).values
del ma, valid, above

adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
elv = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
pkv = pk.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
rows = []
for h in (5, 20):
    R = np.full(adjv.shape, np.nan)
    R[:T - h] = (1 + g1[1:T - h + 1]) * adjv[h:T] / adjv[1:T - h + 1] - 1
    for m in ("上市", "上櫃"):
        ci = np.array([cix[c] for c in mkt.index[mkt == m] if c in cix])
        Rm = R[:, ci]
        ok = ~np.isnan(Rm)
        pm = pkv[:, ci] & ok & ~lock[:, ci].astype(bool)
        um = elv[:, ci] & ok
        n = pm.sum(axis=1)
        pick = np.where(pm, Rm, 0).sum(axis=1) / np.where(n > 0, n, np.nan)
        univ = np.where(um, Rm, 0).sum(axis=1) / np.where(um.sum(axis=1) > 0, um.sum(axis=1), np.nan)
        for t in range(start, T - h):
            if n[t] > 0 and not np.isnan(univ[t]):
                rows.append((t, m, h, (pick[t] - univ[t]) * 100, univ[t] * 100))
a = pd.DataFrame(rows, columns=["t", "m", "h", "ex", "univ"])
a["date"] = dates[a.t.values]
b = np.array([BR[m][t] for t, m in zip(a.t, a.m)])
r_ = np.floor(b + 0.5)
a["z"] = np.where(np.isnan(b), np.nan, np.where(r_ < 35, 0, np.where(r_ <= 50, 1, 2)))
print(f"{len(a)} 列，{time.time() - t0:.0f}s", flush=True)


def summ(d):
    o = {}
    for m in ("上市", "上櫃"):
        x = d[d.m == m]
        o[m] = {f"d{h}": round(float(x[x.h == h].ex.mean()), 2) for h in (5, 20)}
        o[m].update({f"n{h}": int((x.h == h).sum()) for h in (5, 20)})
    return o


res = {"period": f"{dates[start].year}/{dates[start].month}～{a.date.max().year}/{a.date.max().month}", "days": int(a[a.h == 5].t.nunique()),
       "overall": summ(a), "recent": summ(a[a.date >= "2024-10-01"]), "before": summ(a[a.date < "2024-10-01"])}
res["by_year"] = {int(y): summ(d) for y, d in a.groupby(a.date.dt.year)}
bb = {}
for m in ("上市", "上櫃"):
    for lab, d in (("全期", a), ("2024/10 以後", a[a.date >= "2024-10-01"]), ("2024/10 以前", a[a.date < "2024-10-01"])):
        x = d[d.m == m]
        bb[f"{m} {lab}"] = {f"d{h}": [round(float(x[(x.h == h) & (x.z == z)].ex.mean()), 2) for z in (0, 1, 2)] for h in (5, 20)}
        bb[f"{m} {lab}"]["days"] = [int(((x.h == 5) & (x.z == z)).sum()) for z in (0, 1, 2)]
        bb[f"{m} {lab}"]["univ20"] = [round(float(x[(x.h == 20) & (x.z == z)].univ.mean()), 2) for z in (0, 1, 2)]
res["by_breadth"] = bb
# 20 日超額的滾動兩年（約 23 個月），看最近兩年排第幾
roll = []
for s in pd.date_range("2014-03-01", "2024-10-01", freq="MS"):
    d = a[(a.date >= s) & (a.date <= s + pd.DateOffset(months=24)) & (a.h == 20)]
    roll.append((s.strftime("%Y-%m"), round(float(d.ex.mean()), 2)))
roll.sort(key=lambda x: -x[1])
res["roll20_top"] = roll[:5]
res["roll20_rank_2024_10"] = [s for s, _ in roll].index("2024-10") + 1
res["roll20_n"] = len(roll)
json.dump(res, open("out/site_numbers3.json", "w"), ensure_ascii=False, indent=1)
a.to_pickle("out/site_numbers3_rows.pkl")
print(json.dumps({k: res[k] for k in ("period", "days", "overall", "recent", "before")}, ensure_ascii=False))
for k, v in bb.items():
    print(k, v)
for y, v in res["by_year"].items():
    print(y, " ".join(f"{m} {v[m]['d5']:+.2f}/{v[m]['d20']:+.2f}" for m in ("上市", "上櫃")))
print("滾動兩年 20 日超額前 5：", res["roll20_top"], "；2024/10 那段排第", res["roll20_rank_2024_10"], "/", res["roll20_n"])
print(f"完成 {time.time() - t0:.0f}s")
