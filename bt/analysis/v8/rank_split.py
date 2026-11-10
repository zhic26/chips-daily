"""名單前 10 名和第 11～20 名，12 年下來 5／20 日超額差多少（算法同網站回測：隔天開盤買、開盤鎖漲停不算、對照同市場合格股）。
另外看照現行賣出規則（掉出前 80 名賣、最多 60 天）的每筆淨報酬和超額。結果存 out/rank_split.json"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
pkv = pk.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
elv = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
lockb = lock.astype(bool)
adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
rank_in_list = np.zeros(pkv.shape, dtype=np.int16)
for m in ("上市", "上櫃"):
    ci = np.array([cix[c] for c in mkt.index[mkt == m] if c in cix])
    for t in range(T):
        js = ci[pkv[t, ci]]
        if len(js):
            order = js[np.argsort(-SC[t, js])]
            rank_in_list[t, order] = np.arange(1, len(order) + 1)
rows = []
for h in (5, 20):
    R = np.full(adjv.shape, np.nan)
    R[:T - h] = (1 + g1[1:T - h + 1]) * adjv[h:T] / adjv[1:T - h + 1] - 1
    for m in ("上市", "上櫃"):
        ci = np.array([cix[c] for c in mkt.index[mkt == m] if c in cix])
        Rm = R[:, ci]
        ok = ~np.isnan(Rm)
        um = elv[:, ci] & ok
        univ = np.where(um, Rm, 0).sum(axis=1) / np.where(um.sum(axis=1) > 0, um.sum(axis=1), np.nan)
        rk = rank_in_list[:, ci]
        for t in range(start, T - h):
            if np.isnan(univ[t]):
                continue
            for grp, lo, hi in (("1-10", 1, 10), ("11-20", 11, 20), ("1-20", 1, 20)):
                sel = (rk[t] >= lo) & (rk[t] <= hi) & ok[t] & ~lockb[t, ci]
                if sel.any():
                    rows.append((t, m, h, grp, (Rm[t, sel].mean() - univ[t]) * 100, int(sel.sum())))
a = pd.DataFrame(rows, columns=["t", "m", "h", "grp", "ex", "n"])
a["date"] = dates[a.t.values]
res = {}
for lab, d in (("12年", a), ("2024/10以後", a[a.date >= "2024-10-01"]), ("2024/10以前", a[a.date < "2024-10-01"])):
    res[lab] = {m: {grp: {f"d{h}": round(float(d[(d.m == m) & (d.grp == grp) & (d.h == h)].ex.mean()), 2) for h in (5, 20)} for grp in ("1-10", "11-20", "1-20")}
                for m in ("上市", "上櫃")}
# 每年 20 日：前 10 名贏第 11～20 名的年數
yy = {}
for m in ("上市", "上櫃"):
    d = a[(a.m == m) & (a.h == 20)]
    p = d.pivot_table(index=d.date.dt.year, columns="grp", values="ex", aggfunc="mean")
    yy[m] = {int(y): [round(float(r["1-10"]), 2), round(float(r["11-20"]), 2)] for y, r in p.iterrows()}
res["每年20日_前10_vs_11到20"] = yy
# 現行賣出規則每筆（用 long_trades.pkl），依名次分組
tr = pd.read_pickle("out/long_trades.pkl")
tr["i"] = np.searchsorted(dates.values, tr.date.values)
tr["j"] = [cix[c] for c in tr.code]
tr["rk"] = rank_in_list[tr.i.values, tr.j.values]
per = lambda d, c: round(d[c].mean() / d.days.mean() * 20 * 100, 2)  # noqa: E731
res["現行規則每20日"] = {g: {"淨": per(d, "net"), "超額": per(d, "exc"), "勝率": int(round((d.net > 0).mean() * 100)), "筆數": len(d)}
                     for g, d in (("1-10", tr[(tr.rk >= 1) & (tr.rk <= 10)]), ("11-20", tr[tr.rk >= 11]), ("全部", tr))}
json.dump(res, open("out/rank_split.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
print("完成", f"{time.time() - t0:.0f}s")
