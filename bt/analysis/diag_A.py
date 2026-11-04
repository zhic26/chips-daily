"""檢查策略 A（營收創新高＋法人，每月前 5 名）報酬是不是資料錯誤造成的：每年報酬、最賺的交易、持有期間有沒有超過漲跌停的單日報酬。"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
lockv = lock.astype(bool)
elv2 = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
nh = (rev > rev.shift(1).rolling(48, min_periods=48).max())
nh.index = pd.to_datetime(nh.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)
NH = nh.reindex(nh.index.union(dates)).ffill().reindex(dates).reindex(columns=cols).fillna(False).values.astype(bool)
f3 = (P["f"].fillna(0).rolling(3).sum() > 0).values
t3 = (P["t"].fillna(0).rolling(3).sum() > 0).values
S = 40 * f3 + 60 * t3
vt = (avg * P["close"]).values
rv_ = r.reindex(index=dates, columns=cols).values
names = P["name"]
tA = int(np.searchsorted(dates.values, np.datetime64("2017-02-11")))
days = []
seen = set()
for t in range(tA, T):
    k = (dates[t].year, dates[t].month)
    if k not in seen and dates[t].day >= 11:
        seen.add(k); days.append(t)


def run(tiebreak="small", cap=None):
    trades = []
    nav = []
    hold = {}  # j -> (buy t)
    val = 1.0
    for n, t in enumerate(days):
        i = t - 1
        cand = [j for j in np.where(elv2[i] & NH[i] & (S[i] >= 60))[0] if not lockv[i, j] and not np.isnan(AO[t, j])]
        if tiebreak == "small":
            cand.sort(key=lambda j: (-S[i, j], vt[i, j] if not np.isnan(vt[i, j]) else 1e18))
        elif tiebreak == "big":
            cand.sort(key=lambda j: (-S[i, j], -(vt[i, j] if not np.isnan(vt[i, j]) else 0)))
        else:
            cand.sort(key=lambda j: (-S[i, j], -SC[i, j]))
        tgt = cand[:5]
        t2 = days[n + 1] if n + 1 < len(days) else T - 1
        # 每期等權買進、到下一期開盤（最後一期到最後收盤）的報酬，不計換股差異（近似）
        rets = []
        for j in tgt:
            px1 = AO[t, j]
            px2 = AO[t2, j] if (n + 1 < len(days) and not np.isnan(AO[t2, j])) else last_close(t2, j, t)
            g = px2 / px1 - 1
            if cap is not None:
                seg = rv_[t + 1:t2 + 1, j]
                if np.nanmax(np.abs(seg)) > cap if np.isfinite(seg).any() else False:
                    g = np.nan
            if not np.isnan(g):
                rets.append(g - 0.004 * (0 if j in hold else 1))
                trades.append((dates[t].date(), str(cols[j]), names.iloc[j] if hasattr(names, "iloc") else "", round(g * 100, 1),
                               round(float(np.nanmax(np.abs(rv_[t + 1:t2 + 1, j]))) * 100, 1) if np.isfinite(rv_[t + 1:t2 + 1, j]).any() else None))
        hold = {j: t for j in tgt}
        m = np.mean(rets) if rets else 0.0
        val *= 1 + m
        nav.append((dates[t2], val))
    s = pd.Series(dict(nav))
    yrs = (s.index[-1] - dates[days[0]]).days / 365.25
    yearly = (s.groupby(s.index.year).last() / s.groupby(s.index.year).last().shift(1).fillna(1.0) - 1) * 100
    return round((s.iloc[-1] ** (1 / yrs) - 1) * 100, 1), yearly.round(1).to_dict(), trades


for tb in ("small", "score", "big"):
    cagr, yearly, trades = run(tb)
    print(f"\n同分挑 {tb}：近似年化 {cagr}%；每年 {yearly}")
    if tb == "small":
        tr = sorted(trades, key=lambda x: -x[3])
        print("最賺的 12 筆（買進日、代號、名稱、報酬%、持有期間最大單日漲跌%）：")
        for x in tr[:12]:
            print("  ", x)
        big = [x for x in trades if x[4] is not None and x[4] > 10.6]
        print("持有期間有單日 |報酬| > 10.6%（超過漲跌停，可能是除權息或減資調整）的筆數：", len(big), "/", len(trades))
        for x in big[:10]:
            print("   ", x)
cagr, yearly, _ = run("small", cap=0.106)
print(f"\n剔除單日超過 10.6% 的交易後：近似年化 {cagr}%；每年 {yearly}")
print(f"完成 {time.time() - t0:.0f}s")
