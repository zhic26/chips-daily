"""五項權重一起重新檢查（2026-11-05，使用者要求；只做研究、不改網站）。
12 年資料（2014/3～2026/10，沒有千張大戶）。權重以 10 分為一格、五項加起來 100 分，共 1001 組；
每組照網站規則每天挑上市、上櫃各 20 檔（當天法人合計買超、同分比法人買超），隔天開盤買、開盤鎖漲停不算，
算 5／20 日後比同市場合格股（等權）多多少（同 rank_split.py、weight_check.py）。
為了避免挑到只是運氣好的權重，用三種方式驗證：
1. 前後兩半交叉驗證：2014/3～2020/6 挑最好的，拿去 2020/7 以後看；反過來也做。
2. 逐年滾動：每年只用之前的資料挑最好的權重（訓練資料最後 30 天不用，避免 20 日報酬偷看到新年度），用在那一年，2017～2026 接起來。
3. 每一項權重固定在某個值、其他隨意時的平均表現（看趨勢，不挑單一組）。
目標＝上市、上櫃 20 日超額的平均（網站兩個市場用同一組權重）。結果存 out/weights_full.json、out/weights_full.npz"""
import itertools
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
KEYS = ["今日", "5日", "天數", "融資", "營收"]
MARKETS = ("上市", "上櫃")
MI = {m: np.array([cix[c] for c in mkt.index[mkt == m] if c in cix]) for m in MARKETS}
elv_np = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)

# 資料覆蓋率：合格股裡，融資變化、近 3 月營收年增有值的比例（每年）
cov = {}
mch = P["mchg"].reindex(index=dates, columns=cols).values
y3v = Y3.values
yrs = pd.DatetimeIndex(dates).year.values
for y in sorted(set(yrs)):
    r_ = yrs == y
    e = elv_np[r_]
    cov[int(y)] = {"融資有值%": round(float((~np.isnan(mch[r_]) & e).sum() / e.sum() * 100), 1),
                   "營收有值%": round(float((~np.isnan(y3v[r_]) & e).sum() / e.sum() * 100), 1)}
print("覆蓋率", json.dumps(cov, ensure_ascii=False), flush=True)
del mch, y3v

A = [pct(tot / avg), pct(inst5d / (avg * 5)), pct(days), pct(-madd5.fillna(0) / avg), pct(Y3).fillna(0.5)]
A = [a.reindex(index=dates, columns=cols).values for a in A]
totv = tot.reindex(index=dates, columns=cols).fillna(0).values
pool = elv_np & (totv > 0)
tb = np.clip(totv, 0, None) * 1e-9  # 同分時法人買超大的優先（同 bt_lib.top_picks）
lockb = lock.astype(bool)
adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
FW = {}
for h in (5, 20):
    R = np.full(adjv.shape, np.nan)
    R[:T - h] = (1 + g1[1:T - h + 1]) * adjv[h:T] / adjv[1:T - h + 1] - 1
    FW[h] = R
# 每個市場先切好，之後每組權重只做加總、挑前 20 名
SL = {}
for m in MARKETS:
    ci = MI[m]
    uni = {}
    for h in (5, 20):
        Rm = FW[h][:, ci]
        um = elv_np[:, ci] & ~np.isnan(Rm)
        uni[h] = np.where(um, Rm, 0).sum(axis=1) / np.where(um.sum(axis=1) > 0, um.sum(axis=1), np.nan)
    SL[m] = {"A": [np.ascontiguousarray(a[:, ci]) for a in A], "pool": pool[:, ci], "tb": tb[:, ci], "lock": lockb[:, ci],
             "R": {h: np.ascontiguousarray(FW[h][:, ci]) for h in (5, 20)}, "uni": uni}
del A, FW
print("準備完成", f"{time.time() - t0:.0f}s", flush=True)


def run(w):
    """回傳 [h(5,20), 市場, 日] 的超額（%）；沒有名單或報酬還沒出來的日子是 NaN。"""
    out = np.full((2, 2, T), np.nan, dtype=np.float32)
    for mi, m in enumerate(MARKETS):
        s = SL[m]
        S = s["tb"].copy()
        for wk, a in zip(w, s["A"]):
            if wk:
                S += wk * a
        S = np.where(s["pool"] & ~np.isnan(S), S, -np.inf)
        idx = np.argpartition(-S, 19, axis=1)[:, :20]
        valid = np.take_along_axis(S, idx, axis=1) > -np.inf
        lk = np.take_along_axis(s["lock"], idx, axis=1)
        for hi, h in enumerate((5, 20)):
            vals = np.take_along_axis(s["R"][h], idx, axis=1)
            ok = valid & ~lk & ~np.isnan(vals)
            n = ok.sum(axis=1)
            mean = np.where(n > 0, np.where(ok, vals, 0).sum(axis=1) / np.maximum(n, 1), np.nan)
            ex = (mean - s["uni"][h]) * 100
            ex[:start] = np.nan
            ex[T - h:] = np.nan
            out[hi, mi] = ex
    return out


CAND = {"現行（10/10/30/15/20）": (10, 10, 30, 15, 20), "拿掉融資": (10, 10, 30, 0, 20), "今日加到 20": (20, 10, 30, 15, 20),
        "拿掉融資、今日加到 20": (20, 10, 30, 0, 20), "五項平均": (20, 20, 20, 20, 20), "只看天數＋營收": (0, 0, 30, 0, 20),
        "只看天數": (0, 0, 1, 0, 0), "只看營收": (0, 0, 0, 0, 1), "只看今日": (1, 0, 0, 0, 0)}
grid = [w for w in itertools.product(range(0, 101, 10), repeat=5) if sum(w) == 100]
allw = list(CAND.values()) + grid
E = np.full((len(allw), 2, 2, T), np.nan, dtype=np.float32)
for i, w in enumerate(allw):
    E[i] = run(w)
    if i == 0:
        d = pd.DatetimeIndex(dates)
        print("現行 12 年（應接近 weight_check 的 30 分：上市 0.427、上櫃 0.479）",
              [round(float(np.nanmean(E[0, 1, mi])), 3) for mi in range(2)], flush=True)
    if i % 100 == 0:
        print(i, "/", len(allw), f"{time.time() - t0:.0f}s", flush=True)
np.savez_compressed("out/weights_full.npz", E=E, w=np.array(allw), dates=dates.values.astype("datetime64[D]").astype(str))
print("全部跑完", f"{time.time() - t0:.0f}s", flush=True)

dn = dates.values
PER = {"12年": (None, None), "前半 2014/3～2020/6": (None, "2020-07-01"), "後半 2020/7～": ("2020-07-01", None),
       "2024/10 以前（現行權重的樣本外）": (None, "2024-10-01"), "2024/10 以後（調權重用）": ("2024-10-01", None)}


def mask(lo, hi):
    m_ = np.ones(T, bool)
    if lo:
        m_ &= dn >= np.datetime64(lo)
    if hi:
        m_ &= dn < np.datetime64(hi)
    return m_


def avgp(X, lo=None, hi=None):
    return np.nanmean(X[..., mask(lo, hi)], axis=-1)


nC = len(CAND)
G = E[nC:]
gw = np.array(grid)
obj = {k: avgp(G[:, 1], *v).mean(axis=1) for k, v in PER.items()}  # 組數 × 期間：上市、上櫃 20 日平均
res = {"覆蓋率": cov, "候選": {}, "交叉驗證": {}, "逐年滾動": {}, "每項權重": {}, "12年前10組": []}
for (name, w), Xi in zip(CAND.items(), E[:nC]):
    r_ = {}
    for k, v in PER.items():
        x = avgp(Xi, *v)  # [h, m]
        o = float(x[1].mean())
        r_[k] = {"上市20": round(float(x[1, 0]), 3), "上櫃20": round(float(x[1, 1]), 3), "上市5": round(float(x[0, 0]), 3), "上櫃5": round(float(x[0, 1]), 3),
                 "目標": round(o, 3), "排在1001組的前%": round(float((obj[k] > o).mean() * 100), 1)}
    res["候選"][name] = r_
# 逐年：每個候選跟現行比，20 日（兩市場平均）
yr = pd.DatetimeIndex(dates).year.values
cur = E[0, 1].mean(axis=0)
for (name, w), Xi in zip(CAND.items(), E[:nC]):
    xx = Xi[1].mean(axis=0)
    ys = {}
    for y in range(2014, 2027):
        mm = yr == y
        if np.isfinite(xx[mm]).any():
            ys[y] = [round(float(np.nanmean(xx[mm])), 2), round(float(np.nanmean(cur[mm])), 2)]
    res["候選"][name]["每年（這組、現行）"] = ys
    res["候選"][name]["贏現行的年數"] = f"{sum(a > b for a, b in ys.values())}/{len(ys)}"
# 1. 交叉驗證
for tr, te in (("前半 2014/3～2020/6", "後半 2020/7～"), ("後半 2020/7～", "前半 2014/3～2020/6")):
    o_tr, o_te = obj[tr], obj[te]
    b = int(np.nanargmax(o_tr))
    top20 = np.argsort(-o_tr)[:20]
    res["交叉驗證"][f"{tr} 挑 → {te}"] = {
        "挑到的權重": dict(zip(KEYS, map(int, gw[b]))), "訓練期": round(float(o_tr[b]), 3), "測試期": round(float(o_te[b]), 3),
        "訓練期前 20 組在測試期的平均": round(float(o_te[top20].mean()), 3),
        "現行在測試期": res["候選"]["現行（10/10/30/15/20）"][te]["目標"],
        "1001 組在測試期的中位數": round(float(np.nanmedian(o_te)), 3)}
# 2. 逐年滾動
wf, cu = {}, {}
for y in range(2017, 2027):
    trm = dn < np.datetime64(f"{y}-01-01") - np.timedelta64(30, "D")
    tem = yr == y
    o_tr = np.nanmean(G[:, 1][..., trm], axis=-1).mean(axis=1)
    b = int(np.nanargmax(o_tr))
    o_te = float(np.nanmean(G[b, 1][..., tem], axis=-1).mean())
    wf[y] = {"挑到的權重": dict(zip(KEYS, map(int, gw[b]))), "那一年": round(o_te, 3), "現行那一年": round(float(np.nanmean(cur[tem])), 3)}
res["逐年滾動"] = {"每年": wf, "平均（滾動挑）": round(float(np.mean([v["那一年"] for v in wf.values()])), 3),
               "平均（現行）": round(float(np.mean([v["現行那一年"] for v in wf.values()])), 3),
               "滾動贏現行的年數": f"{sum(v['那一年'] > v['現行那一年'] for v in wf.values())}/{len(wf)}"}
# 3. 每項權重固定在某個值時，其他組合的平均
for k, key in enumerate(KEYS):
    res["每項權重"][key] = {p: {str(v): round(float(np.nanmean(obj[p][gw[:, k] == v])), 3) for v in range(0, 60, 10)} for p in PER}
for b in np.argsort(-obj["12年"])[:10]:
    res["12年前10組"].append({"權重": dict(zip(KEYS, map(int, gw[b]))), "12年": round(float(obj["12年"][b]), 3),
                          "2024/10 以前": round(float(obj["2024/10 以前（現行權重的樣本外）"][b]), 3),
                          "前半": round(float(obj["前半 2014/3～2020/6"][b]), 3), "後半": round(float(obj["後半 2020/7～"][b]), 3)})
json.dump(res, open("out/weights_full.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
print("完成", f"{time.time() - t0:.0f}s", flush=True)
