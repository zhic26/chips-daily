"""借券賣出餘額加進分數（第 8 版候選）跟第 7 版比：12 年回測（2026-11-09，使用者要求「回測加入借券餘額分數後的股票會有什麼變化」）。
資料：bt/sbl/<市場>/YYYY-MM-DD.json.gz，2014/1～2026/10 每個交易日（bt/fund12.py sbl … 1）；某天缺檔沿用前一天（最多 5 天）。
借券指標＝借券賣出當日餘額（張）÷ 5 日均量（張），也就是「借券賣出的量要幾天的成交量才回補得完」；
同市場合格股裡排百分位，越少分數越高；不在借券名單上（不能借券賣出）給中間值，跟營收查不到一樣。
第 8 版候選＝第 7 版（法人買超天數 50、營收 35；千張大戶 15 沒有歷史資料，兩邊都不算）＋ w × 借券分數，
另外試幾組可以直接放上網站的整數權重。比的東西跟網站上第 7 版 12 年數字同一套算法（long_setup.py、site_numbers3.py、site_numbers.py）：
  A 名單 5／20 日超額：全期、逐年、前後兩段、最近兩年、依站上季線比例、六次大跌
  B 參考賣法（跌出前 80 名或抱滿 60 天）：每 20 日淨報酬、超額、勝率、最差 5%、平均持有
  C 5 檔、10 檔帳戶模擬：年化、最大回檔
  D 名單換了哪些股票：每天換幾檔、換掉跟換進來的各是什麼樣的股票、20 天後各怎樣、最常被換掉／換進來的股票、最近一天的例子
  E 只當標籤：第 7 版名單裡借券偏多（同市場前 20%）的股票 vs 其他
  F 運氣成分：每天差異的區塊拔靴法、每年只用之前資料選權重再套到下一年
環境變數 QUICK=1：只跑 A、D、E、F（不跑比較慢的 B、C）。結果存 out/sbl_v8.json"""
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
DOC = __doc__
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
BT = "../bt-branch/bt"
SITE = "/home/claude/chips-daily"
QUICK = os.environ.get("QUICK") == "1"
MAIN = os.environ.get("MAIN", "+20")


def say(*a):
    print(*a, f"[{time.time() - t0:.0f}s]", flush=True)


def load(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


r2 = lambda x: None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)  # noqa: E731


def mean(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    return float(x.mean()) if len(x) else np.nan


# ---------- 借券賣出餘額 ----------
N = len(cols)
SBv = np.full((T, N), np.nan, dtype=np.float64)
last, nfile, nfill, badf = {}, {"twse": 0, "tpex": 0}, {"twse": 0, "tpex": 0}, 0
for t, d in enumerate(dates):
    ds = str(d.date())
    for mk in ("twse", "tpex"):
        j = load(f"{BT}/sbl/{mk}/{ds}.json.gz")
        f_ = (j or {}).get("fields") or []
        if j and j.get("rows") and len(f_) > 12 and "當日餘額" in f_[12] and "前日餘額" in f_[8]:
            mp = {c: r[10] / 1000 for c, r in j["rows"].items() if len(r) > 10 and r[10] is not None}  # 第 12 欄（rows 從第 2 欄開始存）
            last[mk] = (t, mp)
            nfile[mk] += 1
        elif mk in last and t - last[mk][0] <= 5:
            badf += bool(j)
            mp = last[mk][1]
            nfill[mk] += 1
        else:
            continue
        for c, v in mp.items():
            jj = cix.get(c)
            if jj is not None:
                SBv[t, jj] = v
say("借券檔案", nfile, "沿用前一天", nfill, "欄位不對", badf, "交易日", T)

avgv = avg.reindex(index=dates, columns=cols).values
SBL = pd.DataFrame(np.where(avgv > 0, SBv / np.where(avgv > 0, avgv, 1), np.nan), index=dates, columns=cols)
PS = pct(SBL)                   # 0＝借券最少、1＝最多（同市場合格股）
GOOD = (1 - PS).fillna(0.5)     # 借券分數：越少越高；查不到給中間值
PSv, SBLv = PS.values, SBL.values
# 對照：借券改除以 60 日均量（避免「最近量突然放大」讓借券天數變小）、同規模裡比借券、量能放大、前 20 天漲幅
avg60 = vol.where(vol > 0).rolling(60, min_periods=40).mean().reindex(index=dates, columns=cols).values
GOOD60 = (1 - pct(pd.DataFrame(np.where(avg60 > 0, SBv / np.where(avg60 > 0, avg60, 1), np.nan), index=dates, columns=cols))).fillna(0.5)
SURGE = pct(pd.DataFrame(avgv / np.where(avg60 > 0, avg60, np.nan), index=dates, columns=cols)).fillna(0.5)
MOM = pct((C / C.shift(20) - 1).reindex(index=dates, columns=cols)).fillna(0.5)
elv0 = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
size_v = (avg * C).reindex(index=dates, columns=cols).values
gsn = np.full((T, N), np.nan)
for m_ in ("上市", "上櫃"):
    ci_ = np.array([cix[c] for c in mkt.index[mkt == m_] if c in cix])
    for t in range(T):
        ok = elv0[t, ci_] & ~np.isnan(SBLv[t, ci_]) & ~np.isnan(size_v[t, ci_])
        if ok.sum() < 50:
            continue
        jj = ci_[ok]
        b = np.minimum((pd.Series(size_v[t, jj]).rank(method="first").values - 1) * 5 // ok.sum(), 4)
        for k in range(5):
            g = jj[b == k]
            if len(g) < 3:
                continue
            r_ = pd.Series(SBLv[t, g]).rank(method="average").values
            gsn[t, g] = 1 - (r_ - 1) / (len(g) - 1)
GOODSN = pd.DataFrame(gsn, index=dates, columns=cols).fillna(0.5)
del avg60, size_v, gsn
FAC = {"借券": GOOD, "借券÷60日均量": GOOD60, "借券（同規模裡比）": GOODSN, "量能放大（對照）": SURGE, "前20天漲幅（對照）": MOM}
elv = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
lockb = lock.astype(bool)
MK = {m: np.array([cix[c] for c in mkt.index[mkt == m] if c in cix]) for m in ("上市", "上櫃")}
mkt_j = mkt.reindex(cols).values
YR = dates.year.values
cov = {}
for m, ci in MK.items():
    e = elv[start:, ci]
    sb = SBv[start:, ci]
    lv = SBLv[start:, ci]
    have = e & ~np.isnan(sb)
    q80 = [np.nanpercentile(lv[k][e[k] & ~np.isnan(lv[k])], 80) for k in range(0, len(e), 20) if (e[k] & ~np.isnan(lv[k])).sum() > 50]
    cov[m] = {"合格股裡有借券資料%": round(have.sum() / e.sum() * 100, 1), "餘額是0的%": round(((sb == 0) & e).sum() / e.sum() * 100, 1),
              "借券天數中位數（有借券的）": r2(np.median(lv[have & (sb > 0)])), "前20%門檻（天）中位數": r2(np.median(q80))}
say("涵蓋", cov)

# ---------- 報酬、對照組、站上季線比例 ----------
adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
RET = {}
for h in (5, 20):
    R_ = np.full(adjv.shape, np.nan)
    R_[:T - h] = (1 + g1[1:T - h + 1]) * adjv[h:T] / adjv[1:T - h + 1] - 1
    RET[h] = R_
del g1
UNI = {}
for h in (5, 20):
    for m, ci in MK.items():
        Rm = RET[h][:, ci]
        um = elv[:, ci] & ~np.isnan(Rm)
        UNI[h, m] = np.where(um, Rm, 0).sum(1) / np.where(um.sum(1) > 0, um.sum(1), np.nan)
ma = C.rolling(60, min_periods=55).mean()
valid = C.notna() & ma.notna()
above = (C > ma) & valid
Z = {}
for m in ("上市", "上櫃"):
    c = mkt.index[mkt == m]
    nv = valid[c].sum(axis=1)
    b = (above[c].sum(axis=1) / nv * 100).where(nv >= 50).values
    rb = np.floor(b + 0.5)
    Z[m] = np.where(np.isnan(b), np.nan, np.where(rb < 35, 0, np.where(rb <= 50, 1, 2)))
del ma, valid, above
taiex = pd.Series({d: v["加權指數"]["close"] for d, v in st["idx"].items() if "加權指數" in (v or {})}).reindex(dates).ffill()
CRASH = [("2015 年中股災", "2015-04-27", "2015-08-24"), ("2018 年 10 月股災", "2018-09-28", "2018-12-28"),
         ("2020 年疫情崩跌", "2020-01-20", "2020-03-19"), ("2022 年空頭", "2022-01-05", "2022-10-25"),
         ("2024 年 7～8 月急跌", "2024-07-11", "2024-08-05"), ("2025 年關稅急跌", "2025-03-01", "2025-04-09")]
DV = dates.values
HALF1 = dates >= pd.Timestamp("2020-07-01")
RECENT = dates >= pd.Timestamp("2024-10-01")


def daily_ex(pkv, h, m):
    """site_numbers3 的算法：每天名單（扣掉隔天鎖漲停）平均報酬減同市場合格股平均，%。回傳 (超額, 名單本身報酬)。"""
    ci = MK[m]
    Rm = RET[h][:, ci]
    pm = pkv[:, ci] & ~np.isnan(Rm) & ~lockb[:, ci]
    n = pm.sum(1)
    pick = np.where(pm, Rm, 0).sum(1) / np.where(n > 0, n, np.nan)
    ex = (pick - UNI[h, m]) * 100
    raw = pick * 100
    ex[:start] = np.nan
    ex[T - h:] = np.nan
    raw[np.isnan(ex)] = np.nan
    return ex, raw


def pick_mask(pkv, m, h=20):
    ci = MK[m]
    pm = pkv[:, ci] & ~np.isnan(RET[h][:, ci]) & ~lockb[:, ci]
    pm[:start] = False
    pm[T - h:] = False
    return pm


def list_stats(pkv):
    out, ser = {}, {}
    for m, ci in MK.items():
        ex5, _ = daily_ex(pkv, 5, m)
        ex20, raw20 = daily_ex(pkv, 20, m)
        ser[m] = ex20
        pm = pick_mask(pkv, m)
        r = RET[20][:, ci][pm]
        sbl_pick = SBLv[:, ci][pm]
        o = {"d5": r2(mean(ex5)), "d20": r2(mean(ex20)), "20天賺錢%": r2((r - COST > 0).mean() * 100),
             "20天跌超過10%的比例": r2((r < -0.10).mean() * 100), "20天漲超過20%的比例": r2((r > 0.20).mean() * 100),
             "名單借券天數中位數": r2(np.nanmedian(sbl_pick)),
             "前段2014～2020/6": r2(mean(ex20[~HALF1])), "後段2020/7～": r2(mean(ex20[HALF1])),
             "最近兩年2024/10～": r2(mean(ex20[RECENT])), "2024/10以前": r2(mean(ex20[~RECENT])),
             "逐年": {int(y): r2(mean(ex20[YR == y])) for y in range(2014, 2027)},
             "依站上季線<35/35～50/>50": [r2(mean(ex20[Z[m] == k])) for k in (0, 1, 2)],
             "大跌（名單本身20天報酬／超額）": {nm: [r2(mean(raw20[(DV >= np.datetime64(a)) & (DV <= np.datetime64(b))])),
                                           r2(mean(ex20[(DV >= np.datetime64(a)) & (DV <= np.datetime64(b))]))] for nm, a, b in CRASH}}
        newin = (pkv[1:, ci] & ~pkv[:-1, ci]).sum(1)[start:]
        o["每天新進名單幾檔"] = r2(newin.mean())
        out[m] = o
    return out, ser


def build(wd, wr, ws, fac="借券"):
    S_ = wd * PD + wr * PR + ws * FAC[fac]
    pkd = B.top_picks(S_.where(el), {"instNet": tot}, mkt)
    pkv = pkd.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
    return S_, pkv


def ranks(S_):
    RKd = pd.DataFrame(np.nan, index=dates, columns=cols)
    for m in ("上市", "上櫃"):
        c = mkt.index[mkt == m]
        RKd[c] = S_[c].where(el[c]).rank(axis=1, ascending=False, method="first")
    return RKd.values


def trades_of(pkv):
    return [(i, j, mkt_j[j]) for i in range(start, T - MAXH - 2) for j in np.where(pkv[i])[0]]


def rule_stats(trs, RKv, rank_lim=80, hold=MAXH):
    """site_numbers.py 的 run（跌出前 rank_lim 名隔天開盤賣，最多抱 hold 天；每筆扣 0.4%）。"""
    rows = []
    for i, j, m in trs:
        e = i + 1
        px = AO[e, j]
        if np.isnan(px) or np.isnan(AC[i, j]) or lock[i, j]:
            continue
        x, out, at_open, why = None, None, False, "max"
        for t in range(e, min(i + hold, T - 2) + 1):
            c = AC[t, j]
            if np.isnan(c):
                continue
            if rank_lim and not RKv[t, j] <= rank_lim and t < i + hold:
                x, at_open, why = t + 1, True, "rank"
                out = AO[x, j] if not np.isnan(AO[x, j]) else c
                break
        if x is None:
            x = i + hold
            out = last_close(x, j, e)
        g = out / px - 1
        rows.append((i, m, g - COST, g - bench(m, e, x, at_open), x - i, why))
    a = pd.DataFrame(rows, columns=["i", "m", "net", "exc", "days", "why"])
    per = lambda d, v: d[v].mean() / d.days.mean() * 20 * 100 if len(d) else np.nan  # noqa: E731
    yr = YR[a.i.values]
    dd = DV[a.i.values]
    o = {"筆數": len(a), "平均持有": r2(a.days.mean()), "每20日淨%": r2(per(a, "net")), "每20日超額%": r2(per(a, "exc")),
         "勝率%": r2((a.net > 0).mean() * 100), "最差5%": r2(np.percentile(a.net, 5) * 100),
         "上市每20日超額%": r2(per(a[a.m == "上市"], "exc")), "上櫃每20日超額%": r2(per(a[a.m == "上櫃"], "exc")),
         "逐年每20日超額%": {int(y): r2(per(a[yr == y], "exc")) for y in np.unique(yr)},
         "大跌每20日淨／超額": {nm: [r2(per(a[(dd >= np.datetime64(s0)) & (dd <= np.datetime64(s1))], "net")),
                                  r2(per(a[(dd >= np.datetime64(s0)) & (dd <= np.datetime64(s1))], "exc"))] for nm, s0, s1 in CRASH}}
    return o


BUY, SELL = 0.0005, 0.0035


def sim(K, pkv, SCv, RKv):
    """site_numbers.py 的 K 檔帳戶模擬（每天補，賣出照參考規則）。"""
    cash, pos, val = 1.0, {}, np.full(T, np.nan)
    for t in range(start + 1, T):
        for j in [j for j, p in pos.items() if p[3]]:
            sh, i0, e0, _ = pos.pop(j)
            px = AO[t, j] if not np.isnan(AO[t, j]) else last_close(t - 1, j, e0)
            cash += sh * px * (1 - SELL)
        i = t - 1
        free = K - len(pos)
        if free > 0:
            cand = [j for j in np.where(pkv[i])[0] if j not in pos and not lock[i, j] and not np.isnan(AO[t, j])]
            cand.sort(key=lambda j: -SCv[i, j])
            value = cash + sum(p[0] * last_close(i, j, p[2]) for j, p in pos.items())
            for j in cand[:free]:
                amt = min(value / K, cash)
                if amt <= 1e-9:
                    break
                pos[j] = [amt * (1 - BUY) / AO[t, j], i, t, False]
                cash -= amt
        v = cash
        for j, p in list(pos.items()):
            c = AC[t, j]
            v += p[0] * (c if not np.isnan(c) else last_close(t, j, p[2]))
            if np.isnan(c):
                continue
            if t - p[1] >= MAXH:
                cash += p[0] * c * (1 - SELL)
                pos.pop(j)
            elif not RKv[t, j] <= 80:
                p[3] = True
        val[t] = v
    return pd.Series(val[start + 1:], index=dates[start + 1:]).dropna()


def stat(s):
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    dd = s / s.cummax() - 1
    tr = dd.idxmin()
    pk_ = s.loc[:tr].idxmax()
    back = s.loc[tr:][s.loc[tr:] >= s.loc[pk_]]
    yearly = s.resample("YE").last()
    yearly = (yearly / yearly.shift(1).fillna(s.iloc[0]) - 1) * 100
    return {"年化%": round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1), "最大回檔%": round(dd.min() * 100, 1),
            "回檔": [f"{pk_.year}/{pk_.month}", f"{tr.year}/{tr.month}", f"{back.index[0].year}/{back.index[0].month}" if len(back) else None],
            "逐年%": {int(k.year): round(float(v), 1) for k, v in yearly.items()}}


# ---------- 各種權重 ----------
PD = pct(days)
PR = pct(Y3).fillna(0.5)
CONF = {"第7版": (50, 35, 0)}
for w in (5, 10, 15, 20, 25, 30, 40):
    CONF[f"+{w}"] = (50, 35, w)
CONF.update({"網站A 天數40/營收30/大戶15/借券15": (40, 30, 15), "網站B 天數40/營收25/大戶15/借券20": (40, 25, 20),
             "網站C 天數45/營收30/大戶10/借券15": (45, 30, 15)})
CHECK = {"對照 借券÷60日均量 +20": (50, 35, 20, "借券÷60日均量"), "對照 借券（同規模裡比）+20": (50, 35, 20, "借券（同規模裡比）"),
         "對照 量能放大 +20": (50, 35, 20, "量能放大（對照）"), "對照 前20天漲幅 +20": (50, 35, 20, "前20天漲幅（對照）")}
CONF.update(CHECK)
res = {"說明": DOC, "期間": f"{dates[start].date()}～{dates[-1].date()}", "借券涵蓋": cov, "設定": {k: list(v) for k, v in CONF.items()},
       "名單": {}, "參考賣法": {}, "帳戶": {}}
PKS, SER = {}, {}
if not QUICK:
    tx = taiex.iloc[start + 1:].dropna()
    res["加權指數（不含息）"] = stat(tx)
for name, cf in CONF.items():
    wd, wr, ws = cf[:3]
    S_, pkv = build(*cf)
    res["名單"][name], SER[name] = list_stats(pkv)
    PKS[name] = pkv
    msg = " ".join(f"{m} d5 {res['名單'][name][m]['d5']:+.2f} d20 {res['名單'][name][m]['d20']:+.2f} 賺錢 {res['名單'][name][m]['20天賺錢%']:.1f}%"
                   for m in ("上市", "上櫃"))
    say(name, msg)
    if not QUICK and name not in CHECK and (name == "第7版" or ws in (10, 15, 20, 25, 30)):
        RKv = ranks(S_)
        res["參考賣法"][name] = rule_stats(trades_of(pkv), RKv)
        say("  參考賣法", {k: v for k, v in res["參考賣法"][name].items() if not isinstance(v, dict)})
        res["帳戶"][name] = {f"{K}檔": stat(sim(K, pkv, S_.values, RKv)) for K in (5, 10)}
        say("  帳戶", {k: {kk: vv for kk, vv in v.items() if kk != "逐年%"} for k, v in res["帳戶"][name].items()})
        del RKv
    del S_
    gc.collect()

# ---------- D：名單換了哪些股票 ----------
names = {}
try:
    import glob as _g
    q = json.load(open(sorted(_g.glob(f"{SITE}/data/daily/*.json"))[-1], encoding="utf-8"))["q"]
    names = {c: v[0] for c, v in q.items()}
    sys.path.insert(0, SITE)
    from chips.sources import INDUSTRY
    comp = json.load(open(f"{SITE}/data/meta/companies.json", encoding="utf-8"))["data"]
    ind = {c: INDUSTRY.get((v or {}).get("industry", ""), "其他") for c, v in comp.items()}
except Exception as e:  # noqa: BLE001
    say("名稱／產業讀不到", repr(e))
    ind = {}
val_amt = (avg * C / 1e5).reindex(index=dates, columns=cols).values  # 5 日均量（張）× 收盤 → 億元
ret20b = (C / C.shift(20) - 1).reindex(index=dates, columns=cols).values * 100


def change_stats(a_name, b_name):
    pa, pb = PKS[a_name], PKS[b_name]
    out = {}
    for m, ci in MK.items():
        A_, B_ = pa[:, ci], pb[:, ci]
        rng = np.zeros(T, bool)
        rng[start:T - 20] = True
        drop, add, keep = A_ & ~B_, B_ & ~A_, A_ & B_
        Rm = RET[20][:, ci]
        okr = ~np.isnan(Rm) & ~lockb[:, ci] & rng[:, None]
        EXm = (Rm - UNI[20, m][:, None]) * 100
        grp = {}
        for g, M in (("被換掉", drop), ("換進來", add), ("兩版都有", keep)):
            Mr = M & okr
            r = Rm[Mr]
            mm = M & rng[:, None]
            inds = pd.Series([ind.get(cols[ci][j], "其他") for j in np.where(mm)[1]]).value_counts(normalize=True).head(5) * 100
            grp[g] = {"每天平均幾檔": r2(mm.sum(1)[start:T - 20].mean()), "20天超額%": r2(EXm[Mr].mean()),
                      "20天賺錢%": r2((r - COST > 0).mean() * 100), "20天跌超過10%的比例": r2((r < -0.10).mean() * 100),
                      "20天漲超過20%的比例": r2((r > 0.20).mean() * 100),
                      "借券天數中位數": r2(np.nanmedian(SBLv[:, ci][mm])), "借券排名中位數（0最少1最多）": r2(np.nanmedian(PSv[:, ci][mm])),
                      "日均成交值中位數（億）": r2(np.nanmedian(val_amt[:, ci][mm])), "之前20天漲幅中位數%": r2(np.nanmedian(ret20b[:, ci][mm])),
                      "產業前五%": {k: round(float(v), 1) for k, v in inds.items()}}
        cnt_d = pd.Series(drop[rng].sum(0), index=cols[ci]).sort_values(ascending=False)
        cnt_a = pd.Series(add[rng].sum(0), index=cols[ci]).sort_values(ascending=False)
        grp["最常被換掉"] = [f"{c} {names.get(c, '')}（{int(n)} 天）" for c, n in cnt_d.head(12).items() if n > 0]
        grp["最常換進來"] = [f"{c} {names.get(c, '')}（{int(n)} 天）" for c, n in cnt_a.head(12).items() if n > 0]
        out[m] = grp
    return out


res["換股"] = {MAIN: change_stats("第7版", MAIN)}
if "+10" in PKS and MAIN != "+10":
    res["換股"]["+10"] = change_stats("第7版", "+10")
say("換股", json.dumps(res["換股"][MAIN], ensure_ascii=False)[:3000])

# 最近一天的例子
S7, _ = build(*CONF["第7版"])
S8, _ = build(*CONF[MAIN])
ex = {}
for t in (T - 1,):
    for m, ci in MK.items():
        def lst(pkv, S_):
            js = [j for j in ci if pkv[t, j]]
            js.sort(key=lambda j: -S_.iat[t, j])
            return js
        l7, l8 = lst(PKS["第7版"], S7), lst(PKS[MAIN], S8)
        fmt = lambda j: f"{cols[j]} {names.get(cols[j], '')}（借券 {SBLv[t, j]:.1f} 天、排名 {PSv[t, j] * 100:.0f}%）" if not np.isnan(SBLv[t, j]) else f"{cols[j]} {names.get(cols[j], '')}（沒有借券資料）"  # noqa: E731
        ex[f"{dates[t].date()} {m}"] = {"被換掉": [fmt(j) for j in l7 if j not in l8], "換進來": [fmt(j) for j in l8 if j not in l7],
                                        "兩版都有": len([j for j in l7 if j in l8])}
res["最近一天的例子"] = ex
say("例子", json.dumps(ex, ensure_ascii=False))
del S7, S8

# ---------- E：只當標籤 ----------
tag = {}
p7 = PKS["第7版"]
for m, ci in MK.items():
    pm = pick_mask(p7, m)
    T_ = pm & (PSv[:, ci] >= 0.8) & (SBv[:, ci] > 0)
    U_ = pm & ~T_
    Rm = RET[20][:, ci]
    EXm = (Rm - UNI[20, m][:, None]) * 100
    tag[m] = {"名單裡平均每天幾檔會被標": r2(T_.sum(1)[start:T - 20].mean()),
              "被標的20天超額%": r2(EXm[T_].mean()), "其他的20天超額%": r2(EXm[U_].mean()),
              "被標的20天賺錢%": r2((Rm[T_] - COST > 0).mean() * 100), "其他的20天賺錢%": r2((Rm[U_] - COST > 0).mean() * 100),
              "被標的跌超過10%": r2((Rm[T_] < -0.1).mean() * 100), "其他的跌超過10%": r2((Rm[U_] < -0.1).mean() * 100),
              "被標的逐年超額": {int(y): r2(EXm[T_ & (YR[:, None] == y)].mean()) for y in range(2014, 2027)},
              "其他的逐年超額": {int(y): r2(EXm[U_ & (YR[:, None] == y)].mean()) for y in range(2014, 2027)}}
res["只當標籤"] = tag
say("標籤", json.dumps(tag, ensure_ascii=False))

# ---------- F：運氣成分 ----------


def block_boot(x, L, nb=2000, seed=0):
    x = x[~np.isnan(x)]
    n = len(x)
    rng = np.random.default_rng(seed)
    k = int(np.ceil(n / L))
    ms = np.empty(nb)
    for b in range(nb):
        s0 = rng.integers(0, n, k)
        idx = ((s0[:, None] + np.arange(L)[None, :]).ravel()[:n]) % n
        ms[b] = x[idx].mean()
    return [r2(v) for v in np.percentile(ms, [5, 50, 95])], r2((ms <= 0).mean() * 100)


boot = {}
for nm in [k for k in CONF if k != "第7版"]:
    boot[nm] = {}
    for m in MK:
        dlt = SER[nm][m] - SER["第7版"][m]
        o = {"每天差異平均": r2(mean(dlt)), "贏的天數%": r2((dlt[~np.isnan(dlt)] > 0).mean() * 100)}
        for L in (60, 250):
            ci_, p0 = block_boot(dlt, L)
            o[f"區塊{L}天_90%區間"] = ci_
            o[f"區塊{L}天_小於等於0的機率%"] = p0
        yrs_win = sum(1 for y in range(2014, 2027) if (res["名單"][nm][m]["逐年"].get(y) or -99) > (res["名單"]["第7版"][m]["逐年"].get(y) or -99))
        o["贏第7版的年數"] = f"{yrs_win}/13"
        boot[nm][m] = o
res["運氣"] = boot
say("運氣", json.dumps({k: boot[k] for k in boot if k in ("+10", "+20", "+30")}, ensure_ascii=False))

# 逐年往前：每年只用之前的年份挑 w（第 7 版＝0 也在候選裡），再套到這一年
grid = {"第7版": 0, **{f"+{w}": w for w in (5, 10, 15, 20, 25, 30, 40)}}
wf = {}
for m in MK:
    rows = []
    for y in range(2016, 2027):
        past = {nm: mean(SER[nm][m][YR < y]) for nm in grid}
        best = max(past, key=past.get)
        cur = mean(SER[best][m][YR == y])
        base = mean(SER["第7版"][m][YR == y])
        rows.append({"年": y, "挑到": best, "那年超額%": r2(cur), "第7版那年%": r2(base)})
    d = pd.DataFrame(rows)
    wf[m] = {"逐年": rows, "平均（挑的）%": r2(d["那年超額%"].mean()), "平均（第7版）%": r2(d["第7版那年%"].mean()),
             "贏的年數": f"{int((d['那年超額%'] > d['第7版那年%']).sum())}/{len(d)}"}
res["逐年往前挑權重"] = wf
say("逐年往前", json.dumps(wf, ensure_ascii=False))

os.makedirs("out", exist_ok=True)
json.dump(res, open("out/sbl_v8.json" if not QUICK else "out/sbl_v8_quick.json", "w"), ensure_ascii=False, indent=1)
say("完成")
