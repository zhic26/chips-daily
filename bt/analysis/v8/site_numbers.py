"""網站要換成十二年回測的數字：進出規則、固定抱 20 天、固定價格出場、K 檔帳戶模擬（含回檔期間）、名單 5/20 日超額。
結果存成 out/site_numbers.json。"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
res = {"period": f"{dates[start].year}/{dates[start].month}～{dates[T - MAXH - 3].year}/{dates[T - MAXH - 3].month}", "trades": len(trades)}


def run(rank_lim, stop, tp, hold=MAXH):
    rows = []
    for i, j, m in trades:
        e = i + 1
        px = AO[e, j]
        if np.isnan(px) or np.isnan(AC[i, j]) or lock[i, j]:
            continue
        lo_px = px * (1 - stop) if stop else None
        hi_px = px * (1 + tp) if tp else None
        x, out, at_open, why = None, None, False, "max"
        for t in range(e, min(i + hold, T - 2) + 1):
            c = AC[t, j]
            if np.isnan(c):
                continue
            hit = None
            if rank_lim and not RK[t, j] <= rank_lim:
                hit = "rank"
            if lo_px and c < lo_px:
                hit = "stop"
            elif hi_px and c >= hi_px:
                hit = "tp"
            if hit and t < i + hold:
                x, at_open, why = t + 1, True, hit
                out = AO[x, j] if not np.isnan(AO[x, j]) else c
                break
        if x is None:
            x = i + hold
            out = last_close(x, j, e)
        g = out / px - 1
        rows.append((g - COST, g - bench(m, e, x, at_open), x - i, why))
    a = pd.DataFrame(rows, columns=["net", "exc", "days", "why"])
    per = lambda v: v.mean() / a.days.mean() * 20 * 100  # noqa: E731
    return {"hold": round(a.days.mean(), 1), "per20": round(per(a.net), 2), "excess20": round(per(a.exc), 2),
            "win": int(round((a.net > 0).mean() * 100)), "worst5": round(float(np.percentile(a.net, 5)) * 100, 1),
            "full": int(round((a.why == "max").mean() * 100)) if rank_lim else None}


res["rule"] = run(80, None, None)
res["hold20"] = run(None, None, None, hold=20)
print("規則", res["rule"], "抱20", res["hold20"], f"{time.time() - t0:.0f}s", flush=True)
price = {}
for name, rl, s_, tp in [("現行＋跌7%停損", 80, 0.07, None), ("現行＋跌10%停損", 80, 0.10, None), ("現行＋跌15%停損", 80, 0.15, None),
                         ("現行＋漲15%停利", 80, None, 0.15), ("現行＋漲30%停利", 80, None, 0.30),
                         ("跌7%漲10%", None, 0.07, 0.10), ("跌8%漲15%", None, 0.08, 0.15), ("跌10%漲20%", None, 0.10, 0.20), ("跌10%漲30%", None, 0.10, 0.30)]:
    price[name] = run(rl, s_, tp)["per20"]
    print(name, price[name], flush=True)
res["price"] = price

# K 檔帳戶模擬
BUY, SELL = 0.0005, 0.0035
pkv = pk.values
fow = np.array([i == 0 or dates[i].isocalendar()[1] != dates[i - 1].isocalendar()[1] for i in range(T)])
taiex = pd.Series({d: v["加權指數"]["close"] for d, v in st["idx"].items() if "加權指數" in (v or {})}).reindex(dates).ffill().values


def sim(K, weekly=False, rng=None):
    cash, pos, val = 1.0, {}, np.full(T, np.nan)
    for t in range(start + 1, T):
        for j in [j for j, p in pos.items() if p[3]]:
            sh, i0, e0, _ = pos.pop(j)
            px = AO[t, j] if not np.isnan(AO[t, j]) else last_close(t - 1, j, e0)
            cash += sh * px * (1 - SELL)
        i = t - 1
        free = K - len(pos)
        if free > 0 and (not weekly or fow[t]):
            cand = [j for j in np.where(pkv[i])[0] if j not in pos and not lock[i, j] and not np.isnan(AO[t, j])]
            if rng is None:
                cand.sort(key=lambda j: -SC[i, j])
            else:
                rng.shuffle(cand)
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
            elif not RK[t, j] <= 80:
                p[3] = True
        val[t] = v
    return pd.Series(val[start + 1:], index=dates[start + 1:]).dropna()


def stat(s):
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    dd = s / s.cummax() - 1
    tr = dd.idxmin()
    pk_ = s.loc[:tr].idxmax()
    back = s.loc[tr:][s.loc[tr:] >= s.loc[pk_]]
    return [round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1), round(dd.min() * 100, 1),
            f"{pk_.year}/{pk_.month}", f"{tr.year}/{tr.month}", f"{back.index[0].year}/{back.index[0].month}" if len(back) else None]


tx = pd.Series(taiex[start + 1:], index=dates[start + 1:]).dropna()
res["taiex"] = stat(tx)
res["slots"] = {}
for K in (3, 5, 10):
    o = {"daily": stat(sim(K)), "weekly": stat(sim(K, True))}
    rr = np.array([stat(sim(K, rng=np.random.default_rng(sd)))[:2] for sd in range(200)])
    o["rand"] = [round(float(x), 1) for x in np.percentile(rr[:, 0], [10, 50, 90])]
    o["randDD"] = round(float(np.median(rr[:, 1])), 1)
    o["lose"] = int(round((rr[:, 0] < res["taiex"][0]).mean() * 100))
    res["slots"][str(K)] = o
    print(K, o, f"{time.time() - t0:.0f}s", flush=True)
res["slotPeriod"] = f"{dates[start + 1].year}/{dates[start + 1].month}～{dates[-1].year}/{dates[-1].month}"
json.dump(res, open("out/site_numbers.json", "w"), ensure_ascii=False, indent=1)
print("完成", f"{time.time() - t0:.0f}s")
