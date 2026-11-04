"""深挖：把網路上找到的幾個方向，用網站 12 年資料測（每月投入 1 份錢，跟同期間「每月買加權」比）。
A. 鉅亨易策略（2022）：月營收創 48 個月新高＋近 3 日外資買超 40 分、投信買超 60 分，≥60 分才買，每月換股、買前 5 名（同分挑成交值小的）。
B. 網站名單小資版（每月 1 檔、抱 60 天）加個股濾網：股價在自己 120 日均線上（趨勢）、波動低於當天合格股中位數（低波動）、再加盤勢濾網。
C. Gayed & Bilello（2016）槓桿輪動：加權在 200 日均線上抱 2 倍、跌破換現金；也看 1 倍。槓桿每年扣 1.5%，換手各扣 0.2%。
加權不含股息（0050 有配息會再好一點），個股有還原股息；來回成本 0.4%。結果存 out/deep.json"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
pkv = pk.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
lockv = lock.astype(bool)
elv2 = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
tx = pd.Series({d: v["加權指數"]["close"] for d, v in st["idx"].items() if "加權指數" in (v or {})}).reindex(dates).ffill().values
txs = pd.Series(tx)
ma200 = txs.rolling(200, min_periods=180).mean().values
Cc = P["close"]
ma = Cc.rolling(60, min_periods=55).mean()
valid = Cc.notna() & ma.notna()
above = (Cc > ma) & valid
c_tw = mkt.index[mkt == "上市"]
tot_ = valid[c_tw].sum(axis=1)
BR = (above[c_tw].sum(axis=1) / tot_ * 100).where(tot_ >= 50).values
del ma, valid, above
ACdf = pd.DataFrame(AC, index=dates, columns=cols)
ma120 = ACdf.rolling(120, min_periods=100).mean().values
vol60 = r.reindex(index=dates, columns=cols).rolling(60, min_periods=50).std().values
volmed = np.nanmedian(np.where(elv2, vol60, np.nan), axis=1)
# 月營收創 48 個月新高（次月 11 日起才能用）
nh = (rev > rev.shift(1).rolling(48, min_periods=48).max())
nh.index = pd.to_datetime(nh.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)
NH = nh.reindex(nh.index.union(dates)).ffill().reindex(dates).reindex(columns=cols).fillna(False).values.astype(bool)
f3 = (P["f"].fillna(0).rolling(3).sum() > 0).values
t3 = (P["t"].fillna(0).rolling(3).sum() > 0).values
SCORE_A = 40 * f3 + 60 * t3
value_traded = (avg * P["close"]).values  # 5 日均量（張）× 收盤，當市值的替代
print("準備好", f"{time.time() - t0:.0f}s", flush=True)


def xirr(flows):
    def npv(x):
        return sum(a / (1 + x) ** (d / 365.25) for d, a in flows)
    lo, hi = -0.99, 3.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return round(mid * 100, 1)


def summarize(nav, flows, t_from):
    s = pd.Series(nav, index=dates[t_from:T]).dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return {"twr": round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1), "mdd": round((s / s.cummax() - 1).min() * 100, 1),
            "irr": xirr(flows), "mult": round(flows[-1][1] / -sum(a for _, a in flows[:-1]), 2), "from": str(s.index[0].date())}


def month_days(t_from, day=1):
    """每月第一個交易日（day=1）或每月 11 日起的第一個交易日（day=11）。"""
    out, seen = [], set()
    for t in range(t_from, T):
        key = (dates[t].year, dates[t].month)
        if key not in seen and dates[t].day >= day:
            seen.add(key)
            out.append(t)
    return out


def dca_index(days, t_from):
    units, flows = 0.0, []
    nav = np.full(T - t_from, np.nan)
    ds = set(days)
    idx_u = 0.0
    for t in range(t_from, T):
        if t in ds:
            v_pre = idx_u * tx[t - 1]
            units += 1.0 / (v_pre / units) if units > 0 else 1.0
            idx_u += 1.0 / tx[t]
            flows.append(((dates[t] - dates[t_from]).days, -1.0))
        nav[t - t_from] = idx_u * tx[t] / units if units > 0 else np.nan
    flows.append(((dates[T - 1] - dates[t_from]).days, idx_u * tx[T - 1]))
    return summarize(nav, flows, t_from)


BUY, SELL = 0.0005, 0.0035


def strat_A(days, t_from, regime=False):
    """每月換股：前 5 名等權；沒入選的賣掉、新入選的買進；regime=True 時站上季線 ≤50% 的月份整份改抱加權。"""
    cash, units, idx_u, hold = 0.0, 0.0, 0.0, {}
    nav = np.full(T - t_from, np.nan)
    flows, picks_n, rets = [], [], []
    ds = set(days)
    entry = {}
    for t in range(t_from, T):
        if t in ds:
            i = t - 1
            v_pre = cash + idx_u * tx[i] + sum(sh * last_close(i, j, e) for j, (sh, e) in hold.items())
            units += 1.0 / (v_pre / units) if units > 0 else 1.0
            flows.append(((dates[t] - dates[t_from]).days, -1.0))
            cash += 1.0
            if regime and not BR[i] > 50:
                target = []
            else:
                cand = [j for j in np.where(elv2[i] & NH[i] & (SCORE_A[i] >= 60))[0] if not lockv[i, j] and not np.isnan(AO[t, j])]
                cand.sort(key=lambda j: (-SCORE_A[i, j], value_traded[i, j] if not np.isnan(value_traded[i, j]) else 1e18))
                target = cand[:5]
            picks_n.append(len(target))
            # 先全部賣到開盤（留在名單裡的不動）
            for j in list(hold):
                if j not in target:
                    sh, e = hold.pop(j)
                    px = AO[t, j] if not np.isnan(AO[t, j]) else last_close(i, j, e)
                    cash += sh * px * (1 - SELL)
                    rets.append(px / entry.pop(j) * (1 - BUY) * (1 - SELL) - 1)
            if idx_u > 0 and target:  # 從加權換回個股
                cash += idx_u * tx[i]
                idx_u = 0.0
            if target:
                value = cash + sum(sh * AO[t, j] for j, (sh, e) in hold.items() if not np.isnan(AO[t, j]))
                each = value / len(target)
                for j in target:
                    cur = hold[j][0] * AO[t, j] if j in hold else 0.0
                    need = each - cur
                    if need > 1e-9 and cash > 1e-9:
                        amt = min(need, cash)
                        sh = amt * (1 - BUY) / AO[t, j]
                        if j in hold:
                            hold[j] = (hold[j][0] + sh, hold[j][1])
                        else:
                            hold[j] = (sh, t)
                            entry[j] = AO[t, j]
                        cash -= amt
            else:
                idx_u += cash / tx[t]
                cash = 0.0
        v = cash + idx_u * tx[t] + sum(sh * last_close(t, j, e) for j, (sh, e) in hold.items())
        nav[t - t_from] = v / units if units > 0 else np.nan
    final = cash + idx_u * tx[T - 1] + sum(sh * last_close(T - 1, j, e) for j, (sh, e) in hold.items())
    flows.append(((dates[T - 1] - dates[t_from]).days, final))
    out = summarize(nav, flows, t_from)
    a = np.array(rets)
    out.update({"每月平均檔數": round(float(np.mean(picks_n)), 1), "賣出筆數": len(a), "每筆勝率": int(round((a > 0).mean() * 100)) if len(a) else None,
                "每筆中位數": round(float(np.median(a)) * 100, 1) if len(a) else None})
    return out


def strat_B(days, t_from, trend=False, lowvol=False, regime=False, N=1, H=60):
    cash, units, idx_u, pos = 0.0, 0.0, 0.0, []
    nav = np.full(T - t_from, np.nan)
    flows, rets = [], []
    ds = set(days)
    for t in range(t_from, T):
        if t in ds:
            i = t - 1
            v_pre = cash + idx_u * tx[i] + sum(p[1] * last_close(i, p[0], p[2]) for p in pos)
            units += 1.0 / (v_pre / units) if units > 0 else 1.0
            flows.append(((dates[t] - dates[t_from]).days, -1.0))
            cash += 1.0
            pick = []
            if not regime or BR[i] > 50:
                held = {p[0] for p in pos}
                cand = [j for j in np.where(pkv[i])[0] if j not in held and not lockv[i, j] and not np.isnan(AO[t, j])]
                if trend:
                    cand = [j for j in cand if not np.isnan(ma120[i, j]) and AC[i, j] > ma120[i, j]]
                if lowvol:
                    cand = [j for j in cand if not np.isnan(vol60[i, j]) and vol60[i, j] <= volmed[i]]
                cand.sort(key=lambda j: -SC[i, j])
                pick = cand[:N]
            if pick:
                amt = cash / len(pick)
                for j in pick:
                    pos.append([j, amt * (1 - BUY) / AO[t, j], t, i, AO[t, j]])
                cash = 0.0
            else:
                idx_u += cash / tx[t]
                cash = 0.0
        keep = []
        for p in pos:
            if t >= p[3] + H:
                px = last_close(t, p[0], p[2])
                cash += p[1] * px * (1 - SELL)
                rets.append(px / p[4] * (1 - BUY) * (1 - SELL) - 1)
            else:
                keep.append(p)
        pos = keep
        v = cash + idx_u * tx[t] + sum(p[1] * last_close(t, p[0], p[2]) for p in pos)
        nav[t - t_from] = v / units if units > 0 else np.nan
    final = cash + idx_u * tx[T - 1] + sum(p[1] * last_close(T - 1, p[0], p[2]) for p in pos)
    flows.append(((dates[T - 1] - dates[t_from]).days, final))
    out = summarize(nav, flows, t_from)
    a = np.array(rets)
    out.update({"每筆勝率": int(round((a > 0).mean() * 100)), "每筆中位數": round(float(np.median(a)) * 100, 1), "最差5%": round(float(np.percentile(a, 5)) * 100, 1), "筆數": len(a)})
    return out


def strat_C(days, t_from, lev=2.0, filt=True, fee=0.015, switch=0.002):
    """每月投入；部位每天乘上 lev 倍加權日報酬（扣年費）；filt=True 時前一天收盤在 200 日線下就抱現金。"""
    units, val = 0.0, 0.0
    nav = np.full(T - t_from, np.nan)
    flows = []
    ds = set(days)
    state_on = True
    switches = 0
    for t in range(t_from, T):
        on = (not filt) or (tx[t - 1] > ma200[t - 1])
        if t > t_from:
            rr = tx[t] / tx[t - 1] - 1
            if on:
                val *= max(0.0, 1 + lev * rr - fee / 250)
        if on != state_on:
            switches += 1
            val *= (1 - switch)
            state_on = on
        if t in ds:
            units += 1.0 / (val / units) if units > 0 and val > 0 else 1.0
            val += 1.0
            flows.append(((dates[t] - dates[t_from]).days, -1.0))
        nav[t - t_from] = val / units if units > 0 else np.nan
    flows.append(((dates[T - 1] - dates[t_from]).days, val))
    out = summarize(nav, flows, t_from)
    out["每年換手次數"] = round(switches / ((dates[T - 1] - dates[t_from]).days / 365.25), 1)
    return out


res = {}
# A：營收新高 48 個月要到 2017/2 才有，比較期間從那時開始
tA = int(np.searchsorted(dates.values, np.datetime64("2017-02-11")))
daysA = month_days(tA, day=11)
res["A 期間對照：每月買加權（2017/2 起）"] = dca_index(daysA, tA)
res["A 營收創新高＋法人（每月換前 5 名）"] = strat_A(daysA, tA)
res["A 同上＋盤勢濾網"] = strat_A(daysA, tA, regime=True)
for k in list(res)[-3:]:
    print(k, res[k], f"{time.time() - t0:.0f}s", flush=True)
# B：2014/4 起
tB = start + 1
daysB = [t for t in range(tB, T) if dates[t].month != dates[t - 1].month]
res["B 期間對照：每月買加權（2014/4 起）"] = dca_index(daysB, tB)
for name, kw in [("B 小資版（對照）", {}), ("B 小資版＋趨勢（股價在 120 日線上）", dict(trend=True)),
                 ("B 小資版＋低波動", dict(lowvol=True)), ("B 小資版＋趨勢＋低波動", dict(trend=True, lowvol=True)),
                 ("B 小資版＋盤勢濾網", dict(regime=True)), ("B 小資版＋盤勢＋趨勢＋低波動", dict(regime=True, trend=True, lowvol=True)),
                 ("B 每月 3 檔＋盤勢＋趨勢＋低波動", dict(regime=True, trend=True, lowvol=True, N=3))]:
    res[name] = strat_B(daysB, tB, **kw)
    print(name, res[name], f"{time.time() - t0:.0f}s", flush=True)
# C：200 日線要 2014/10 才有
tC = int(np.searchsorted(dates.values, np.datetime64("2014-10-01")))
daysC = [t for t in range(tC, T) if dates[t].month != dates[t - 1].month]
for name, kw in [("C 每月買加權（1 倍、不擇時）", dict(lev=1.0, filt=False, fee=0.0)), ("C 1 倍＋200 日線", dict(lev=1.0, filt=True, fee=0.0)),
                 ("C 2 倍、不擇時", dict(lev=2.0, filt=False)), ("C 2 倍＋200 日線", dict(lev=2.0, filt=True))]:
    res[name] = strat_C(daysC, tC, **kw)
    print(name, res[name], f"{time.time() - t0:.0f}s", flush=True)
json.dump(res, open("out/deep.json", "w"), ensure_ascii=False, indent=1, default=float)
print("完成", f"{time.time() - t0:.0f}s")
