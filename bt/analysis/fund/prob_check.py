"""上漲機率做不做得出來（2026-11-08）。用第 7 版分數（不含千張大戶，0～85 分）的 12 年資料：
1) 合格股、各分數區間、名單股：隔天開盤買、第 20 個交易日收盤賣（還原權息），扣 0.4% 後賺錢的比例、贏過同市場合格股平均的比例
2) 依上市站上季線比例分組（現在約 10%）
3) 每天橫切面的 AUC：拿分數猜「誰會賺」「誰會贏過平均」，0.5＝丟銅板
4) 加權指數持有不同天數的上漲比例（不含息），以及站上季線比例很低時買的結果
結果存 out/prob_check.json"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())

# 上市站上季線比例（跟網站盤勢提醒同定義）
ma = C.rolling(60, min_periods=55).mean()
valid = C.notna() & ma.notna()
above = (C > ma) & valid
c_tse = mkt.index[mkt == "上市"]
nv = valid[c_tse].sum(axis=1)
BR = (above[c_tse].sum(axis=1) / nv * 100).where(nv >= 50).values
del ma, valid, above
gc.collect()

H = 20
adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
R = np.full(adjv.shape, np.nan)
R[:T - H] = (1 + g1[1:T - H + 1]) * adjv[H:T] / adjv[1:T - H + 1] - 1
elm = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
pkm = pk.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
lockb = lock.astype(bool)

rank_in_list = np.zeros(pkm.shape, dtype=np.int16)
for m in ("上市", "上櫃"):
    ci = np.array([cix[c] for c in mkt.index[mkt == m] if c in cix])
    for t in range(T):
        js = ci[pkm[t, ci]]
        if len(js):
            order = js[np.argsort(-SC[t, js])]
            rank_in_list[t, order] = np.arange(1, len(order) + 1)
parts = []
for m in ("上市", "上櫃"):
    ci = np.array([cix[c] for c in mkt.index[mkt == m] if c in cix])
    Rm = R[:, ci]
    M = elm[:, ci] & ~np.isnan(Rm)
    M[:start] = False
    M[T - H:] = False
    tt, jj = np.nonzero(M)
    cnt = M.sum(axis=1)
    univ = np.where(M, Rm, 0).sum(axis=1) / np.where(cnt > 0, cnt, np.nan)
    gj = ci[jj]
    parts.append(pd.DataFrame({
        "t": tt, "m": m, "sc": SC[tt, gj], "r": Rm[tt, jj], "univ": univ[tt],
        "pick": pkm[tt, gj] & ~lockb[tt, gj], "rk": rank_in_list[tt, gj], "br": BR[tt]}))
df = pd.concat(parts, ignore_index=True)
del parts
gc.collect()
df["net"] = df.r - COST
df["up"] = df.net > 0
df["beat"] = df.r > df.univ
df["ex"] = (df.r - df.univ) * 100
print(f"{len(df)} 筆股票日，{df.t.nunique()} 天，{time.time() - t0:.0f}s", flush=True)


def stat(d):
    return {"n": int(len(d)), "賺錢%": round(float(d.up.mean() * 100), 1), "贏平均%": round(float(d.beat.mean() * 100), 1),
            "平均超額%": round(float(d.ex.mean()), 2), "平均報酬%": round(float(d.r.mean() * 100), 2),
            "中位數報酬%": round(float(d.r.median() * 100), 2)}


res = {"說明": "隔天開盤買、第 20 個交易日收盤賣；賺錢＝扣 0.4% 來回成本後大於 0；贏平均＝報酬高於同一天同市場合格股的平均（不扣成本）；分數是第 7 版不含千張大戶（滿分 85，網站分數約再加 0～15）",
       "期間": f"{dates[start].date()}～{dates[T - H - 1].date()}"}
bins = [-1, 20, 40, 60, 70, 75, 80, 86]
labs = ["0-20", "20-40", "40-60", "60-70", "70-75", "75-80", "80以上"]
df["sb"] = pd.cut(df.sc, bins=bins, labels=labs, right=False)
for m in ("上市", "上櫃"):
    d = df[df.m == m]
    o = {"全部合格股": stat(d), "名單股": stat(d[d.pick])}
    o["名單 1-5 名"] = stat(d[d.pick & (d.rk >= 1) & (d.rk <= 5)])
    o["名單 6-10 名"] = stat(d[d.pick & (d.rk >= 6) & (d.rk <= 10)])
    o["名單 11-20 名"] = stat(d[d.pick & (d.rk >= 11)])
    o["名單且分數80以上"] = stat(d[d.pick & (d.sc >= 80)])
    o["分數區間"] = {lab: stat(d[d.sb == lab]) for lab in labs}
    res[m] = o
# 依上市站上季線比例
bb = [-1, 15, 35, 50, 101]
bl = ["<15", "15-35", "35-50", ">=50"]
df["bz"] = pd.cut(df.br, bins=bb, labels=bl, right=False)
res["依站上季線比例"] = {m: {lab: {"全部": stat(df[(df.m == m) & (df.bz == lab)]), "名單": stat(df[(df.m == m) & (df.bz == lab) & df.pick]),
                            "天數": int(df[(df.m == m) & (df.bz == lab)].t.nunique())} for lab in bl} for m in ("上市", "上櫃")}
# 每年：名單股和全部的賺錢比例
df["y"] = dates[df.t.values].year
res["每年賺錢%"] = {m: {int(y): [round(float(g[g.pick].up.mean() * 100), 1), round(float(g.up.mean() * 100), 1)]
                        for y, g in df[df.m == m].groupby("y")} for m in ("上市", "上櫃")}

# 橫切面 AUC
def auc_by_day(d, ycol):
    d = d[["t", "sc", ycol]].copy()
    d["rk"] = d.groupby("t").sc.rank(method="average")
    d["yr"] = d.rk * d[ycol]
    g = d.groupby("t").agg(n=("sc", "size"), p=(ycol, "sum"), s=("yr", "sum"))
    g = g[(g.p > 0) & (g.p < g.n)]
    a = (g.s - g.p * (g.p + 1) / 2) / (g.p * (g.n - g.p))
    return {"平均AUC": round(float(a.mean()), 3), "AUC大於0.5的天數%": round(float((a > 0.5).mean() * 100), 1), "天數": int(len(a))}


res["AUC"] = {m: {"猜會不會贏平均": auc_by_day(df[df.m == m], "beat"), "猜會不會賺錢": auc_by_day(df[df.m == m], "up")} for m in ("上市", "上櫃")}

# 時間序列：每天的賺錢比例差多少（大盤的影響）
dd = df[df.m == "上市"].groupby("t").up.mean()
res["上市每天賺錢比例的分布%"] = {q: round(float(dd.quantile(qq) * 100), 1) for q, qq in (("10分位", .1), ("25分位", .25), ("中位數", .5), ("75分位", .75), ("90分位", .9))}

# 加權指數持有期間（收盤到收盤，不含息）
tx = pd.Series({d: v["加權指數"]["close"] for d, v in st["idx"].items() if "加權指數" in (v or {})}).reindex(dates).ffill().values
txo = {}
for h in (20, 60, 120, 250, 500, 750):
    ok = np.arange(T - h)
    ok = ok[~np.isnan(tx[ok]) & ~np.isnan(tx[ok + h])]
    up = tx[ok + h] > tx[ok]
    low = ok[np.nan_to_num(BR[ok], nan=100) < 15]
    txo[f"{h}日"] = {"上漲%": round(float(up.mean() * 100), 1), "n": int(len(ok)),
                    "站上季線<15%時買_上漲%": round(float((tx[low + h] > tx[low]).mean() * 100), 1) if len(low) else None,
                    "站上季線<15%的天數": int(len(low)),
                    "平均報酬%": round(float((tx[ok + h] / tx[ok] - 1).mean() * 100), 1)}
res["加權指數"] = txo
res["站上季線<15%的日期區段"] = sorted({str(dates[i].date())[:7] for i in range(T) if not np.isnan(BR[i]) and BR[i] < 15})
json.dump(res, open("out/prob_check.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
print("完成", f"{time.time() - t0:.0f}s")
