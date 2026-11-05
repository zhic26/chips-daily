"""法人買超天數（連買一致性）權重 30 會不會太高（2026-11-05，使用者的問題）。
12 年回測裡只改這一項的權重（0～50，其他 4 項不變；12 年版本沒有千張大戶），看名單 5／20 日超額；
另外算每一項指標單獨的 IC（在「當天法人買超」的股票裡，跟 5／20 日後報酬的等級相關）。
算法同網站回測（rank_split.py）：隔天開盤買、開盤鎖漲停不算、對照同市場合格股等權。結果存 out/weight_check.json"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
A = {"今日": pct(tot / avg), "5日": pct(inst5d / (avg * 5)), "天數": pct(days), "融資": pct(-madd5.fillna(0) / avg), "營收": pct(Y3).fillna(0.5)}
elv_np = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
pool_np = elv_np & (tot.reindex(index=dates, columns=cols).fillna(0).values > 0)
lockb = lock.astype(bool)
adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
FW = {}
for h in (5, 20):
    R = np.full(adjv.shape, np.nan)
    R[:T - h] = (1 + g1[1:T - h + 1]) * adjv[h:T] / adjv[1:T - h + 1] - 1
    FW[h] = R
MI = {m: np.array([cix[c] for c in mkt.index[mkt == m] if c in cix]) for m in ("上市", "上櫃")}
UNI = {}
for h in (5, 20):
    for m, ci in MI.items():
        Rm = FW[h][:, ci]
        um = elv_np[:, ci] & ~np.isnan(Rm)
        UNI[(h, m)] = np.where(um, Rm, 0).sum(axis=1) / np.where(um.sum(axis=1) > 0, um.sum(axis=1), np.nan)
PERIODS = (("12年", None, None), ("2024/10以前（樣本外）", None, "2024-10-01"), ("2024/10以後（調權重用）", "2024-10-01", None))


def cut(d, lo, hi):
    if lo:
        d = d[d.date >= lo]
    if hi:
        d = d[d.date < hi]
    return d


def evaluate(pkv):
    rows = []
    for h in (5, 20):
        for m, ci in MI.items():
            Rm = FW[h][:, ci]
            ok = ~np.isnan(Rm)
            univ = UNI[(h, m)]
            sel_all = pkv[:, ci] & ok & ~lockb[:, ci]
            for t in range(start, T - h):
                if np.isnan(univ[t]) or not sel_all[t].any():
                    continue
                rows.append((t, m, h, (Rm[t, sel_all[t]].mean() - univ[t]) * 100))
    a = pd.DataFrame(rows, columns=["t", "m", "h", "ex"])
    a["date"] = dates[a.t.values]
    out = {lab: {m: {f"d{h}": round(float(cut(a, lo, hi)[lambda d: (d.m == m) & (d.h == h)].ex.mean()), 3) for h in (5, 20)} for m in MI}
           for lab, lo, hi in PERIODS}
    d20 = a[a.h == 20]
    yr = d20.groupby([d20.date.dt.year, "m"]).ex.mean().unstack()
    out["每年20日"] = {m: {int(y): round(float(v), 2) for y, v in yr[m].dropna().items()} for m in MI}
    return out


def ic(F, h):
    """每天在法人買超池裡算等級相關，再平均；t 值用不重疊的日子（每 h 天取一天）算，避免重疊高估。"""
    res = {}
    for m, ci in MI.items():
        X = F.reindex(index=dates, columns=cols).values[:, ci]
        Y = FW[h][:, ci]
        mask = pool_np[:, ci] & ~np.isnan(X) & ~np.isnan(Y)
        Xr = pd.DataFrame(np.where(mask, X, np.nan)).rank(axis=1).values
        Yr = pd.DataFrame(np.where(mask, Y, np.nan)).rank(axis=1).values
        xm = np.nanmean(Xr, axis=1, keepdims=True)
        ym = np.nanmean(Yr, axis=1, keepdims=True)
        num = np.nansum((Xr - xm) * (Yr - ym), axis=1)
        den = np.sqrt(np.nansum((Xr - xm) ** 2, axis=1) * np.nansum((Yr - ym) ** 2, axis=1))
        with np.errstate(invalid="ignore", divide="ignore"):
            icd = num / den
        icd[mask.sum(axis=1) < 20] = np.nan
        s = pd.Series(icd, index=dates).iloc[start:T - h]
        out = {}
        for lab, lo, hi in PERIODS:
            x = s
            if lo:
                x = x[x.index >= lo]
            if hi:
                x = x[x.index < hi]
            x = x.dropna()
            nx = x.iloc[::h]
            out[lab] = [round(float(x.mean()), 4), round(float(nx.mean() / nx.std() * np.sqrt(len(nx))), 1), round(float((x > 0).mean() * 100))]
        res[m] = out
    return res


res = {"IC": {}, "權重": {}}
for k, F in A.items():
    res["IC"][k] = {f"d{h}": ic(F, h) for h in (5, 20)}
    print("IC", k, json.dumps(res["IC"][k]["d20"], ensure_ascii=False), f"{time.time() - t0:.0f}s", flush=True)
for w3 in (0, 10, 20, 30, 40, 50):
    S = 10 * A["今日"] + 10 * A["5日"] + w3 * A["天數"] + 15 * A["融資"] + 20 * A["營收"]
    pkw = B.top_picks(S.where(el), {"instNet": tot}, mkt).reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
    res["權重"][str(w3)] = evaluate(pkw)
    print("天數權重", w3, json.dumps({k: v for k, v in res["權重"][str(w3)].items() if k != "每年20日"}, ensure_ascii=False), f"{time.time() - t0:.0f}s", flush=True)
json.dump(res, open("out/weight_check.json", "w"), ensure_ascii=False, indent=1)
print("完成", f"{time.time() - t0:.0f}s", flush=True)
