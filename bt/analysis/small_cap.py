"""小資版回測（2014/3～2026/10）：每月第一個交易日投入 1 份錢，開盤買前一天名單（上市、上櫃合起來照分數排）分數最高的 N 檔
（已經抱著的、開盤鎖漲停的跳過），每檔抱滿 H 個交易日收盤賣，賣掉的錢下個月一起再買。
對照：同樣每月投入 1 份，當天收盤買加權指數（不含股息，0050 實際會因配息再好一點）。
另外跑「從當天名單隨機挑 N 檔」200 次，看運氣的範圍。結果存 out/small_cap.json"""
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


def xirr(flows):
    """flows: [(天數, 金額)]，投入為負、期末為正；回傳年化報酬（%）。"""
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


def stats(nav, flows, trades=None):
    s = pd.Series(nav, index=dates[start + 1:T]).dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    out = {"twr": round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1), "mdd": round((s / s.cummax() - 1).min() * 100, 1),
           "irr": xirr(flows), "mult": round(flows[-1][1] / -sum(a for _, a in flows[:-1]), 2)}
    if trades is not None and len(trades):
        a = np.array(trades)
        out.update({"n": len(a), "win": int(round((a > 0).mean() * 100)), "avg": round(a.mean() * 100, 1), "med": round(float(np.median(a)) * 100, 1),
                    "p5": round(float(np.percentile(a, 5)) * 100, 1), "p95": round(float(np.percentile(a, 95)) * 100, 1)})
    return out


def lastc(t, j, lo):
    return last_close(t, j, lo)


def run(N, H, cost, rng=None):
    BUY = (cost - 0.003) / 2
    SELL = BUY + 0.003
    cash, units, pos = 0.0, 0.0, []  # pos: [j, shares, 買進日 t, 名單日 i, 買價]
    nav = np.full(T - start - 1, np.nan)
    flows, trades = [], []
    fset = set(first)
    for t in range(start + 1, T):
        # 收盤前先處理到期的（抱滿 H 個交易日：名單日 i + H 那天收盤賣）
        if t in fset:
            held_val = sum(p[1] * lastc(t - 1, p[0], p[2]) for p in pos)
            v_pre = cash + held_val
            units += 1.0 / (v_pre / units) if units > 0 else 1.0
            cash += 1.0
            flows.append(((dates[t] - dates[start + 1]).days, -1.0))
            i = t - 1
            held = {p[0] for p in pos}
            cand = [j for j in np.where(pkv[i])[0] if j not in held and not lockv[i, j] and not np.isnan(AO[t, j])]
            if rng is None:
                cand.sort(key=lambda j: -SC[i, j])
            else:
                rng.shuffle(cand)
            pick = cand[:N]
            if pick:
                amt = cash / len(pick)
                for j in pick:
                    pos.append([j, amt * (1 - BUY) / AO[t, j], t, i, AO[t, j]])
                cash = 0.0
        keep = []
        for p in pos:
            if t >= p[3] + H:
                px = lastc(t, p[0], p[2])
                cash += p[1] * px * (1 - SELL)
                trades.append(px / p[4] * (1 - BUY) * (1 - SELL) - 1)
            else:
                keep.append(p)
        pos = keep
        v = cash + sum(p[1] * lastc(t, p[0], p[2]) for p in pos)
        nav[t - start - 1] = v / units if units > 0 else np.nan
    final = cash + sum(p[1] * lastc(T - 1, p[0], p[2]) for p in pos)
    flows.append(((dates[T - 1] - dates[start + 1]).days, final))
    return stats(nav, flows, trades)


def taiex_dca():
    units, flows = 0.0, []
    for t in first:
        units += 1.0 / tx[t]
        flows.append(((dates[t] - dates[start + 1]).days, -1.0))
    flows.append(((dates[T - 1] - dates[start + 1]).days, units * tx[T - 1]))
    nav = tx[start + 1:T] / tx[start + 1]
    return stats(nav, flows)


res = {"period": f"{dates[start + 1].date()}～{dates[T - 1].date()}", "months": len(first), "taiex": taiex_dca(), "runs": {}}
print("加權定期定額", res["taiex"], flush=True)
for N, H, c in [(1, 60, 0.004), (2, 60, 0.004), (3, 60, 0.004), (3, 120, 0.004), (1, 60, 0.01), (3, 60, 0.01)]:
    k = f"N{N}_H{H}_c{c}"
    res["runs"][k] = run(N, H, c)
    print(k, res["runs"][k], f"{time.time() - t0:.0f}s", flush=True)
for N in (1, 3):
    rr = [run(N, 60, 0.004, rng=np.random.default_rng(s)) for s in range(200)]
    irr = np.array([r["irr"] for r in rr])
    mdd = np.array([r["mdd"] for r in rr])
    res["runs"][f"rand_N{N}"] = {"irr_p10_p50_p90": [round(float(x), 1) for x in np.percentile(irr, [10, 50, 90])],
                                 "lose_vs_taiex": int(round((irr < res["taiex"]["irr"]).mean() * 100)), "mdd_med": round(float(np.median(mdd)), 1)}
    print(f"rand N{N}", res["runs"][f"rand_N{N}"], f"{time.time() - t0:.0f}s", flush=True)
json.dump(res, open("out/small_cap.json", "w"), ensure_ascii=False, indent=1)
print("完成", f"{time.time() - t0:.0f}s")
