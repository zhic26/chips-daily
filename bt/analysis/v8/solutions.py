"""網路上找到的幾種「解法」，用網站 12 年資料測（2014/4～2026/10，每月投入 1 份錢）：
1. 核心衛星：每月 80%（或 90%）買加權、20%（10%）照小資版買名單股。
2. 盤勢濾網：小資版只在「上市站上季線比例 > 50%」或「加權在 200 日均線上」的月份買名單股，其他月份那份錢改買加權。
3. 跌深加碼：每月 80% 買加權、20% 先存現金（不計利息），月初加權比前高跌 10% 以上時，把存的錢全部買進。
加權不含股息（0050 有配息會再好一點）；名單股有還原股息。結果存 out/solutions.json"""
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
tx = pd.Series({d: v["加權指數"]["close"] for d, v in st["idx"].items() if "加權指數" in (v or {})}).reindex(dates).ffill().values
first = [t for t in range(start + 1, T) if dates[t].month != dates[t - 1].month]
fset = set(first)
Cc = P["close"]
ma = Cc.rolling(60, min_periods=55).mean()
valid = Cc.notna() & ma.notna()
above = (Cc > ma) & valid
c_tw = mkt.index[mkt == "上市"]
tot = valid[c_tw].sum(axis=1)
BR = (above[c_tw].sum(axis=1) / tot * 100).where(tot >= 50).values
del ma, valid, above
txs = pd.Series(tx)
ma200 = txs.rolling(200, min_periods=180).mean().values
peak = txs.cummax().values


def xirr(flows):
    def npv(r):
        return sum(a / (1 + r) ** (d / 365.25) for d, a in flows)
    lo, hi = -0.99, 3.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return round(mid * 100, 1)


def summarize(nav, flows):
    s = pd.Series(nav, index=dates[start + 1:T]).dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return {"twr": round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1), "mdd": round((s / s.cummax() - 1).min() * 100, 1),
            "irr": xirr(flows), "mult": round(flows[-1][1] / -sum(a for _, a in flows[:-1]), 2)}


def run(N=1, H=60, cost=0.004, core=0.0, filt=None, reserve=0.0, dip=-0.10):
    BUY = (cost - 0.003) / 2
    SELL = BUY + 0.003
    cash, units, idx_u, rsv, pos = 0.0, 0.0, 0.0, 0.0, []
    nav = np.full(T - start - 1, np.nan)
    flows = []
    months_on = months = 0
    for t in range(start + 1, T):
        if t in fset:
            v_pre = cash + rsv + idx_u * tx[t - 1] + sum(p[1] * last_close(t - 1, p[0], p[2]) for p in pos)
            units += 1.0 / (v_pre / units) if units > 0 else 1.0
            flows.append(((dates[t] - dates[start + 1]).days, -1.0))
            months += 1
            if reserve > 0:  # 跌深加碼：只有指數部位
                idx_u += (1 - reserve) / tx[t]
                rsv += reserve
                if tx[t - 1] / peak[t - 1] - 1 <= dip:
                    idx_u += rsv / tx[t]
                    rsv = 0.0
            else:
                idx_u += core / tx[t]
                sleeve = 1.0 - core
                i = t - 1
                ok = filt is None or filt(i)
                if sleeve > 0 and ok:
                    months_on += 1
                    cash += sleeve
                    held = {p[0] for p in pos}
                    cand = [j for j in np.where(pkv[i])[0] if j not in held and not lockv[i, j] and not np.isnan(AO[t, j])]
                    cand.sort(key=lambda j: -SC[i, j])
                    pick = cand[:N]
                    if pick:
                        amt = cash / len(pick)
                        for j in pick:
                            pos.append([j, amt * (1 - BUY) / AO[t, j], t, i])
                        cash = 0.0
                elif sleeve > 0:
                    idx_u += (sleeve + cash) / tx[t]  # 濾網沒過：這份錢（和閒置現金）改買加權
                    cash = 0.0
        keep = []
        for p in pos:
            if t >= p[3] + H:
                cash += p[1] * last_close(t, p[0], p[2]) * (1 - SELL)
            else:
                keep.append(p)
        pos = keep
        v = cash + rsv + idx_u * tx[t] + sum(p[1] * last_close(t, p[0], p[2]) for p in pos)
        nav[t - start - 1] = v / units if units > 0 else np.nan
    final = cash + rsv + idx_u * tx[T - 1] + sum(p[1] * last_close(T - 1, p[0], p[2]) for p in pos)
    flows.append(((dates[T - 1] - dates[start + 1]).days, final))
    out = summarize(nav, flows)
    if filt is not None:
        out["月份用名單"] = f"{months_on}/{months}"
    return out


res = {}
cases = [
    ("加權定期定額", dict(core=1.0)),
    ("小資版 1 檔（對照）", dict()),
    ("核心衛星 80/20", dict(core=0.8)),
    ("核心衛星 90/10", dict(core=0.9)),
    ("小資版＋濾網：站上季線 >50%", dict(filt=lambda i: BR[i] > 50)),
    ("小資版＋濾網：加權在 200 日線上", dict(filt=lambda i: tx[i] > ma200[i])),
    ("核心衛星 80/20＋濾網 >50%", dict(core=0.8, filt=lambda i: BR[i] > 50)),
    ("跌深加碼：80% 定期定額＋20% 等跌 10% 再買", dict(reserve=0.2, dip=-0.10)),
    ("跌深加碼：80%＋20% 等跌 20% 再買", dict(reserve=0.2, dip=-0.20)),
]
for name, kw in cases:
    res[name] = run(**kw)
    print(name, res[name], f"{time.time() - t0:.0f}s", flush=True)
json.dump(res, open("out/solutions.json", "w"), ensure_ascii=False, indent=1)
print("完成")
