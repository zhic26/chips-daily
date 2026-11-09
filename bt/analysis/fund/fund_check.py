"""本益比、殖利率、淨值比、季報 EPS（由本益比反推）、借券賣出：12 年回測（2026-11-09，使用者要求）。
取樣日：bt/raw 全部交易日的第 0、5、10…天（跟 bt/fund12.py 下載的日子一樣），2014/3～2026/9。
每個取樣日：隔天開盤買、第 20 個交易日收盤賣（還原權息），扣 0.4% 後大於 0 算賺錢；超額＝減掉同市場合格股平均。
A 單獨看：每個指標在同市場合格股裡分五組，看 20 日超額、賺錢比例、AUC。
B 加進第 7 版分數（不含千張大戶，滿分 85）：+10 分／+20 分，名單（當天法人買超、前 20 名）的 20 日超額和賺錢比例，前後兩段、逐年。
結果存 out/fund_check.json"""
import glob
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
BT = "../bt-branch/bt"

H = 20
adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
R = np.full(adjv.shape, np.nan)
R[:T - H] = (1 + g1[1:T - H + 1]) * adjv[H:T] / adjv[1:T - H + 1] - 1
elm = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
lockb = lock.astype(bool)
totv = tot.reindex(index=dates, columns=cols).values  # 三大法人買賣超（張）
avgv = avg.reindex(index=dates, columns=cols).values  # 5 日均量（張）
Cv = C.values
S = [t for t in range(start, T - H) if t % 5 == 0]
print(f"取樣 {len(S)} 天：{dates[S[0]].date()}～{dates[S[-1]].date()}", flush=True)
mk_of = {m: np.array([cix[c] for c in mkt.index[mkt == m] if c in cix]) for m in ("上市", "上櫃")}
mdir = {"上市": "twse", "上櫃": "tpex"}


def load(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------- 讀資料：每個取樣日的本益比、淨值比、殖利率、借券賣出餘額 ----------
nS, nC = len(S), len(cols)
PE, PB, DY, SB = (np.full((nS, nC), np.nan) for _ in range(4))
have_val, have_sbl = np.zeros(nS, bool), np.zeros(nS, bool)
sbl_col = {}
for k, t in enumerate(S):
    d = str(dates[t].date())
    for m in ("上市", "上櫃"):
        v = load(f"{BT}/val/{mdir[m]}/{d}.json.gz")
        if v:
            have_val[k] = True
            for code, (pe, pb, y) in v.items():
                j = cix.get(code)
                if j is None:
                    continue
                PE[k, j] = pe if pe is not None else -1.0  # 虧損（證交所本益比空白）記成 -1
                PB[k, j] = pb if pb is not None else np.nan
                DY[k, j] = y if y is not None else 0.0
        s = load(f"{BT}/sbl/{mdir[m]}/{d}.json.gz")
        if s and s.get("rows"):
            if m not in sbl_col:  # 找「借券賣出當日餘額」那一欄
                f = s.get("fields") or []
                idx = [i for i, x in enumerate(f) if "當日餘額" in x]
                sbl_col[m] = (idx[-1] - 2) if idx else None
                print("借券欄位", m, f, "→", sbl_col[m], flush=True)
            ci = sbl_col[m]
            if ci is None:
                continue
            have_sbl[k] = True
            for code, row in s["rows"].items():
                j = cix.get(code)
                if j is not None and ci < len(row) and row[ci] is not None:
                    SB[k, j] = row[ci] / 1000  # 股 → 張
print(f"估值有資料 {have_val.sum()} 天、借券 {have_sbl.sum()} 天，{time.time() - t0:.0f}s", flush=True)

# ---------- 指標 ----------
close_S = Cv[S]
pos = PE > 0
EY = np.where(pos, 1 / np.where(pos, PE, 1), np.where(PE == -1, -0.05, np.nan))      # 盈餘殖利率，虧損最低
BP = np.where(PB > 0, 1 / np.where(PB > 0, PB, 1), np.nan)                          # 淨值市價比
ROE = np.where(pos & (PB > 0), PB / np.where(pos, PE, 1), np.where(PE == -1, -0.05, np.nan))
EPS = np.where(pos, close_S / np.where(pos, PE, 1), np.where(PE == -1, -1.0, np.nan))  # 近四季 EPS（虧損記 -1，只用來判斷正負）


def growth(lag):
    """近四季 EPS 跟 lag 個取樣日前比（52 週＝10.4 個月、13 週＝一季）。轉虧為盈給 +1，由盈轉虧給 -1，限制在 -1～+3。"""
    g = np.full_like(EPS, np.nan)
    a, b = EPS[lag:], EPS[:-lag]
    ok = ~np.isnan(a) & ~np.isnan(b)
    both = ok & (a > 0) & (b > 0)
    g[lag:][both] = np.clip(a[both] / b[both] - 1, -1, 3)
    g[lag:][ok & (a > 0) & (b <= 0)] = 1.0
    g[lag:][ok & (a <= 0) & (b > 0)] = -1.0
    g[lag:][ok & (a <= 0) & (b <= 0)] = -0.5
    return g


EPSG_Y = growth(52)   # 年增（每 5 個交易日取樣，52 個取樣日約一年）
EPSG_Q = growth(13)   # 跟一季前比
avg_S = avgv[S]
SBL_LVL = SB / np.where(avg_S > 0, avg_S, np.nan)                  # 借券賣出餘額是幾天的均量
SBL_CHG = np.full_like(SB, np.nan)
SBL_CHG[1:] = (SB[1:] - SB[:-1]) / np.where(avg_S[1:] > 0, avg_S[1:], np.nan)  # 5 日增減（張）÷ 均量
FACT = {"盈餘殖利率": EY, "淨值市價比": BP, "殖利率": DY, "ROE": ROE, "EPS年增": EPSG_Y, "EPS季變化": EPSG_Q,
        "借券餘額": SBL_LVL, "借券5日增減": SBL_CHG}
# 方向事先定好（不看結果再選）：估值便宜、獲利高、EPS 成長越高越好；借券越少越好
SIGN = {"盈餘殖利率": 1, "淨值市價比": 1, "殖利率": 1, "ROE": 1, "EPS年增": 1, "EPS季變化": 1, "借券餘額": -1, "借券5日增減": -1}

# ---------- 共用：報酬、合格股 ----------
RS = R[S]
ELS = elm[S] & ~np.isnan(RS)
LKS = lockb[S]
TOTS = totv[S]
W0S = SC[S]
YEAR = np.array([dates[t].year for t in S])
HALF = np.array([0 if dates[t] < pd.Timestamp("2020-07-01") else 1 for t in S])


def pct_rows(X, mask):
    """每一列（取樣日）在 mask 裡排百分位 0～1；沒有值的給 NaN。"""
    out = np.full(X.shape, np.nan)
    for k in range(X.shape[0]):
        ok = mask[k] & ~np.isnan(X[k])
        if ok.sum() < 30:
            continue
        r = pd.Series(X[k, ok]).rank(method="average").values
        out[k, ok] = (r - 1) / (ok.sum() - 1)
    return out


def auc_row(score, y):
    ok = ~np.isnan(score)
    s, yy = score[ok], y[ok]
    p = yy.sum()
    n = len(yy)
    if p == 0 or p == n:
        return np.nan
    rk = pd.Series(s).rank(method="average").values
    return (rk[yy].sum() - p * (p + 1) / 2) / (p * (n - p))


res = {"說明": "每 5 個交易日取樣；隔天開盤買、第 20 個交易日收盤賣；賺錢＝扣 0.4% 後大於 0；超額＝減同市場合格股平均；"
              "加進分數＝第 7 版（不含千張大戶）＋w×指標百分位（方向事先定好），名單＝當天法人買超的前 20 名",
       "取樣天數": len(S), "估值天數": int(have_val.sum()), "借券天數": int(have_sbl.sum())}
for m in ("上市", "上櫃"):
    ci = mk_of[m]
    E = ELS[:, ci]
    Rm = RS[:, ci]
    univ = np.array([Rm[k, E[k]].mean() if E[k].any() else np.nan for k in range(nS)])
    EX = (Rm - univ[:, None]) * 100
    UP = (Rm - COST) > 0
    BEAT = Rm > univ[:, None]
    base = W0S[:, ci]
    rows_m = {}

    # ---- A：單獨看 ----
    for name, F in FACT.items():
        Fm = F[:, ci]
        P_ = pct_rows(Fm, E)
        ok = E & ~np.isnan(P_)
        if ok.sum() < 5000:
            rows_m[name] = {"樣本太少": int(ok.sum())}
            continue
        q = np.minimum(np.floor(P_ * 5), 4)
        qs = {}
        for b in range(5):
            sel = ok & (q == b)
            qs[f"Q{b + 1}"] = {"超額%": round(float(EX[sel].mean()), 2), "賺錢%": round(float(UP[sel].mean() * 100), 1)}
        aucs_b = [auc_row(P_[k, E[k]], BEAT[k, E[k]]) for k in range(nS) if (E[k] & ~np.isnan(P_[k])).sum() >= 30]
        aucs_u = [auc_row(P_[k, E[k]], UP[k, E[k]]) for k in range(nS) if (E[k] & ~np.isnan(P_[k])).sum() >= 30]
        halves = {}
        for h in (0, 1):
            hs = ok & (HALF[:, None] == h)
            top, bot = hs & (q == 4), hs & (q == 0)
            halves["前段" if h == 0 else "後段"] = round(float(EX[top].mean() - EX[bot].mean()), 2)
        rows_m[name] = {"五分組": qs, "Q5減Q1超額": round(qs["Q5"]["超額%"] - qs["Q1"]["超額%"], 2),
                        "AUC贏平均": round(float(np.nanmean(aucs_b)), 3), "AUC賺錢": round(float(np.nanmean(aucs_u)), 3),
                        "Q5減Q1分段": halves, "有值比例%": round(float(ok.sum() / E.sum() * 100), 1)}

    # ---- B：加進第 7 版分數 ----
    def picks_stats(score):
        sc = np.where(E & (TOTS[:, ci] > 0), score + np.where(np.isnan(TOTS[:, ci]), 0, TOTS[:, ci]) * 1e-9, np.nan)
        exs, ups, rets, yrs, hfs = [], [], [], [], []
        for k in range(nS):
            okk = ~np.isnan(sc[k])
            if okk.sum() < 20:
                continue
            idx = np.where(okk)[0]
            top = idx[np.argsort(-sc[k, idx])[:20]]
            top = top[~LKS[k, ci[top]]]
            if not len(top):
                continue
            exs.append(EX[k, top].mean())
            ups.append(UP[k, top].mean())
            rets.append(Rm[k, top].mean() * 100)
            yrs.append(YEAR[k])
            hfs.append(HALF[k])
        exs, ups, yrs, hfs = map(np.array, (exs, ups, yrs, hfs))
        by_year = {int(y): round(float(exs[yrs == y].mean()), 2) for y in np.unique(yrs)}
        return {"名單超額%": round(float(exs.mean()), 2), "名單賺錢%": round(float(ups.mean() * 100), 1),
                "前段超額%": round(float(exs[hfs == 0].mean()), 2), "後段超額%": round(float(exs[hfs == 1].mean()), 2),
                "逐年": by_year}

    def combo_auc(score):
        a_b = [auc_row(score[k, E[k]], BEAT[k, E[k]]) for k in range(nS) if E[k].sum() >= 30]
        a_u = [auc_row(score[k, E[k]], UP[k, E[k]]) for k in range(nS) if E[k].sum() >= 30]
        return round(float(np.nanmean(a_b)), 3), round(float(np.nanmean(a_u)), 3)

    b0 = picks_stats(base)
    b0["AUC贏平均"], b0["AUC賺錢"] = combo_auc(np.where(E, base, np.nan))
    comb = {"第7版（不含大戶）": b0}
    for name, F in FACT.items():
        if "五分組" not in rows_m.get(name, {}):
            continue
        P_ = pct_rows(F[:, ci], E)
        sign = SIGN[name]
        Pd = np.where(np.isnan(P_), 0.5, P_ if sign > 0 else 1 - P_)
        for w in (10, 20):
            s = base + w * Pd
            st = picks_stats(s)
            st["AUC贏平均"], st["AUC賺錢"] = combo_auc(np.where(E, s, np.nan))
            yb = sum(1 for y in st["逐年"] if st["逐年"][y] > b0["逐年"].get(y, -99))
            st["贏第7版的年數"] = f"{yb}/{len(st['逐年'])}"
            st["方向"] = "越高越好" if sign > 0 else "越低越好"
            comb[f"{name} +{w}"] = st
    res[m] = {"單獨看": rows_m, "加進分數": comb}
    print(m, "完成", f"{time.time() - t0:.0f}s", flush=True)

# ---------- C：全部指標一起做「上漲機率」模型，逐年往前驗證 ----------
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

PD = pct(days).values[S]
PY = pct(Y3).values[S]
ma = C.rolling(60, min_periods=55).mean()
valid = C.notna() & ma.notna()
above = (C > ma) & valid
c_tse = mkt.index[mkt == "上市"]
nv = valid[c_tse].sum(axis=1)
BRS = (above[c_tse].sum(axis=1) / nv * 100).where(nv >= 50).values[S]
del ma, valid, above
PCT = {"法人買超天數": PD, "營收": PY}
UNIV = np.full((nS, nC), np.nan)
for m in ("上市", "上櫃"):
    ci = mk_of[m]
    E = ELS[:, ci]
    Rm = RS[:, ci]
    UNIV[:, ci] = np.array([Rm[k, E[k]].mean() if E[k].any() else np.nan for k in range(nS)])[:, None]
for name, F in FACT.items():
    A = np.full((nS, nC), np.nan)
    for m in ("上市", "上櫃"):
        ci = mk_of[m]
        A[:, ci] = pct_rows(F[:, ci], ELS[:, ci])
    PCT[name] = A
kk, jj = np.nonzero(ELS & ~np.isnan(UNIV) & ~np.isnan(BRS)[:, None])
otc = np.array([1.0 if mkt[c] == "上櫃" else 0.0 for c in cols])
names_all = list(PCT)
Xall = np.column_stack([np.nan_to_num(PCT[n][kk, jj], nan=0.5) for n in names_all] + [otc[jj], BRS[kk] / 100])
y_up = (RS[kk, jj] - COST) > 0
y_beat = RS[kk, jj] > UNIV[kk, jj]
yr = YEAR[kk]
cols_of = {"只用第7版兩項": [0, 1, len(names_all)], "加上估值、EPS、借券": list(range(len(names_all))) + [len(names_all)],
           "再加上大盤（站上季線比例）": list(range(len(names_all) + 2)),
           "全部＋大盤，用非線性模型": list(range(len(names_all) + 2))}
cres = {}
for tgt, y in (("賺錢", y_up), ("贏平均", y_beat)):
    for lab, fc in cols_of.items():
        pred = np.full(len(y), np.nan)
        for ty in range(2017, int(yr.max()) + 1):
            test = yr == ty
            first_k = kk[test].min() if test.any() else None
            train = (yr < ty) & (kk < (first_k - 4 if first_k is not None else 0))
            if not test.any() or train.sum() < 10000:
                continue
            if "非線性" in lab:
                mdl = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=500,
                                                     l2_regularization=1.0, random_state=0)
            else:
                mdl = LogisticRegression(max_iter=500)
            mdl.fit(Xall[train][:, fc], y[train])
            pred[test] = mdl.predict_proba(Xall[test][:, fc])[:, 1]
        ok = ~np.isnan(pred)
        p, yy, kt = pred[ok], y[ok], kk[ok]
        per_day = []
        for k in np.unique(kt):
            s = kt == k
            if yy[s].any() and not yy[s].all() and s.sum() >= 30:
                per_day.append(roc_auc_score(yy[s], p[s]))
        dec = pd.qcut(p, 10, labels=False, duplicates="drop")
        cres[f"{tgt}｜{lab}"] = {
            "整體AUC": round(float(roc_auc_score(yy, p)), 3), "每天橫切面AUC": round(float(np.mean(per_day)), 3),
            "預測機率5～95分位%": [round(float(np.percentile(p, 5) * 100), 1), round(float(np.percentile(p, 95) * 100), 1)],
            "預測最低一成_實際%": round(float(yy[dec == 0].mean() * 100), 1), "預測最高一成_實際%": round(float(yy[dec == dec.max()].mean() * 100), 1),
            "全部實際%": round(float(yy.mean() * 100), 1), "測試期": "2017～2026 每年只用之前的資料訓練"}
res["上漲機率模型"] = cres
print(json.dumps(cres, ensure_ascii=False, indent=1), flush=True)

json.dump(res, open("out/fund_check.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({m: {k: {kk: vv for kk, vv in v.items() if kk != "逐年"} for k, v in res[m]["加進分數"].items()} for m in ("上市", "上櫃")}, ensure_ascii=False, indent=1))
print(json.dumps({m: {k: {kk: vv for kk, vv in v.items() if kk not in ("五分組",)} for k, v in res[m]["單獨看"].items()} for m in ("上市", "上櫃")}, ensure_ascii=False, indent=1))
print("完成", f"{time.time() - t0:.0f}s")
