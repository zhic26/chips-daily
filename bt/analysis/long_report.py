"""十年回測報告：每年、空頭期間、獲利集中度、帳戶模擬（只抱 K 檔）對加權指數。
用法：python long_report.py（先跑 long_check.py 產生 out/long_trades.pkl）"""
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
a = pd.read_pickle("out/long_trades.pkl")
per = lambda d: d.net.mean() / d.days.mean() * 20 * 100  # noqa: E731
perx = lambda d: d.exc.mean() / d.days.mean() * 20 * 100  # noqa: E731
taiex = pd.Series({d: v["加權指數"]["close"] for d, v in st["idx"].items() if "加權指數" in (v or {})}).reindex(dates).ffill()
out = []


def say(s=""):
    out.append(s)
    print(s, flush=True)


say(f"名單交易 {len(a)} 筆，名單日期 {a.date.min().date()}～{a.date.max().date()}")
say(f"全部：每20日淨 {per(a):.2f}%、超額 {perx(a):.2f}%、勝率 {(a.net > 0).mean():.0%}、平均持有 {a.days.mean():.1f} 天")
w, l = a.net[a.net > 0], a.net[a.net <= 0]
say(f"盈虧比 {w.mean() / -l.mean():.2f}（平均賺 {w.mean() * 100:.1f}%、平均賠 {l.mean() * 100:.1f}%）")
s = a.net.sort_values(ascending=False)
for q in (0.01, 0.05):
    k = int(len(s) * q)
    say(f"最好的 {q:.0%}（{k} 筆）占總淨利 {s.iloc[:k].sum() / s.sum():.0%}；拿掉後每筆淨 {s.iloc[k:].mean() * 100:.2f}%（全部 {s.mean() * 100:.2f}%）")

say("\n每年（依名單日期）：")
a["y"] = a.date.dt.year
ty = taiex.resample("YE").last().pct_change() * 100
ty.index = ty.index.year
ty.loc[taiex.index[0].year] = (taiex.resample("YE").last().iloc[0] / taiex.iloc[0] - 1) * 100
rows = []
for y, d in a.groupby("y"):
    rows.append({"年": y, "筆數": len(d), "每20日淨%": round(per(d), 2), "每20日超額%": round(perx(d), 2),
                 "勝率%": round((d.net > 0).mean() * 100), "加權全年%": round(ty.get(y, np.nan), 1)})
Y = pd.DataFrame(rows)
say(Y.to_string(index=False))

say("\n空頭和急跌期間（名單日期落在這段）：")
for name, s0, s1 in [("2015 年中股災", "2015-04-27", "2015-08-24"), ("2018 年 10 月股災", "2018-09-28", "2018-12-28"),
                     ("2020 年疫情崩跌", "2020-01-20", "2020-03-19"), ("2022 年空頭", "2022-01-05", "2022-10-25"),
                     ("2024 年 7～8 月急跌", "2024-07-11", "2024-08-05"), ("2025 年關稅急跌", "2025-03-01", "2025-04-09")]:
    d = a[(a.date >= s0) & (a.date <= s1)]
    tx = taiex.loc[s0:s1]
    if len(d) == 0 or tx.empty:
        continue
    say(f"  {name}（{s0}～{s1}，加權 {(tx.iloc[-1] / tx.iloc[0] - 1) * 100:+.1f}%）：{len(d)} 筆，每20日淨 {per(d):.2f}%、超額 {perx(d):.2f}%、勝率 {(d.net > 0).mean():.0%}")

ma = taiex.rolling(60, min_periods=55).mean()
up = (taiex > ma).reindex(a.date).values
for k, nm in ((True, "季線上"), (False, "季線下")):
    d = a[up == k]
    say(f"名單那天加權在{nm}：{len(d)} 筆，每20日淨 {per(d):.2f}%、超額 {perx(d):.2f}%")

# ---------- 帳戶模擬 ----------
BUY, SELL = 0.0005, 0.0035
pkv = pk.values
fow = np.array([i == 0 or dates[i].isocalendar()[1] != dates[i - 1].isocalendar()[1] for i in range(T)])
tx = taiex.values


def sim(K, weekly=False, rng=None, end=T - 1):
    cash, pos, val = 1.0, {}, np.full(T, np.nan)
    for t in range(start + 1, end + 1):
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
    return pd.Series(val[start + 1:end + 1], index=dates[start + 1:end + 1]).dropna()


def stat(sr):
    yrs = (sr.index[-1] - sr.index[0]).days / 365.25
    return float(round(((sr.iloc[-1] / sr.iloc[0]) ** (1 / yrs) - 1) * 100, 1)), float(round((sr / sr.cummax() - 1).min() * 100, 1))


def fmt(x):
    return f"年化 {x[0]}%、最大回檔 {x[1]}%"


bt_s = pd.Series(tx[start + 1:], index=dates[start + 1:]).dropna()
ew = {}
for m in ("上市", "上櫃"):
    ew[m] = pd.Series(np.cumprod(1 + U[m][0][start + 1:]), index=dates[start + 1:])
say(f"\n帳戶模擬（{dates[start + 1].date()}～{dates[-1].date()}）：")
say(f"  加權指數（不含股息）：{fmt(stat(bt_s))}")
for m in ("上市", "上櫃"):
    say(f"  {m}合格股等權（含息）：{fmt(stat(ew[m]))}")
curves = {}
for K in (5, 10, 20):
    for weekly in (False, True):
        sr = sim(K, weekly)
        curves[(K, weekly)] = sr
        say(f"  最多 {K} 檔、{'每週一才買' if weekly else '每天有空位就買'}：{fmt(stat(sr))}")
say("\n每年報酬%（最多 10 檔、每天有空位就買 vs 加權）：")
yr = pd.DataFrame({"10 檔": curves[(10, False)].resample("YE").last().pct_change() * 100,
                   "加權": bt_s.resample("YE").last().pct_change() * 100}).round(1)
yr.index = yr.index.year
say(yr.iloc[1:].to_string())
for K in (5, 10):
    res = []
    for seed in range(100):
        res.append(stat(sim(K, False, rng=np.random.default_rng(seed))))
    x = np.array(res)
    say(f"隨機挑名單裡的 {K} 檔（100 次）：年化 10%/50%/90% 分位 {np.percentile(x[:, 0], [10, 50, 90]).round(1)}；"
        f"最大回檔中位 {np.median(x[:, 1]):.1f}%；年化輸給加權的比例 {(x[:, 0] < stat(bt_s)[0]).mean():.0%}")
open("out/long_report.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"完成 {time.time() - t0:.0f}s")
