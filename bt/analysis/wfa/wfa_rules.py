"""逐年盲測第二階段：用盲測挑出的權重（每年只用之前資料挑的）拼成每天的分數，跑網站的參考賣法和小帳戶，
跟固定第 8 版（用整段 12 年挑的權重）在同一段 2017/1～2026/10 比。算法同 site_numbers.py（第 8 版網站數字）。

- 分數：2017 年起每一年用 wfa_grid.py「擴張每年重挑」那一年挑到的六項權重（另外也跑「滾動 5 年每年重挑」）；
  名次也用當時那一組權重算，所以年初換權重時，手上的股票會用新權重判斷有沒有掉出前 80 名（跟網站改版時一樣）。
- 參考賣法：名單隔天開盤買，跌出同市場前 80 名隔天開盤賣，最多抱 60 個交易日，每筆扣 0.4%。
- 小帳戶：3／5／10 檔每天有空位就補（照分數挑），另外從名單隨機挑各 100 次。
- 對照：固定第 8 版、加權指數（不含息），都從 2017/1/3 開始。
結果：out/wfa_rules.json"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())


def say(*a):
    print(*a, f"[{time.time() - t0:.0f}s]", flush=True)


G1 = json.load(open("out/wfa_grid.json", encoding="utf-8"))
KEYS = ["今日", "5日", "天數", "融資", "營收", "借券"]
F = {"今日": pct(tot / avg), "5日": pct(inst5d / (avg * 5)), "天數": pct(days), "融資": pct(-madd5.fillna(0) / avg),
     "營收": pct(Y3).fillna(0.5), "借券": GOOD}
F = {k: v.reindex(index=dates, columns=cols) for k, v in F.items()}
s17 = int(np.searchsorted(dates.values, np.datetime64("2017-01-01")))
YR = dates.year.values


def wf_score(scheme):
    rows = G1["盲測"][scheme]["每段"]
    Sv = np.full((T, len(cols)), np.nan)
    for r in rows:
        y = int(r["測試期"][:4])
        m_ = (YR == y) if y > 2017 else (YR <= 2017)
        w = r["挑到的權重"]
        part = None
        for k in KEYS:
            if w[k]:
                x = w[k] * F[k].values[m_]
                part = x if part is None else part + x
        Sv[m_] = part
    return pd.DataFrame(Sv, index=dates, columns=cols)


def picks_ranks(S):
    pkd = B.top_picks(S.where(el), {"instNet": tot}, mkt)
    RKd = pd.DataFrame(np.nan, index=dates, columns=cols)
    for m in ("上市", "上櫃"):
        c = mkt.index[mkt == m]
        RKd[c] = S[c].where(el[c]).rank(axis=1, ascending=False, method="first")
    return pkd.reindex(index=dates, columns=cols).fillna(False).values.astype(bool), RKd.values


adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
elv_np = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
RET = {}
for h in (5, 20):
    R_ = np.full(adjv.shape, np.nan)
    R_[:T - h] = (1 + g1[1:T - h + 1]) * adjv[h:T] / adjv[1:T - h + 1] - 1
    RET[h] = R_
MKJ = mkt.reindex(cols).values
MK = {m: np.array([cix[c] for c in mkt.index[mkt == m] if c in cix]) for m in ("上市", "上櫃")}


def list_ex(pkv):
    """名單 5／20 日超額（2017 起，每天先平均再對天數平均），用來核對第一階段。"""
    o = {}
    for h in (5, 20):
        for m, ci in MK.items():
            Rm = RET[h][:, ci]
            ok = ~np.isnan(Rm)
            pm = pkv[:, ci] & ok & ~lock[:, ci].astype(bool)
            um = elv_np[:, ci] & ok
            n = pm.sum(1)
            pick = np.where(pm, Rm, 0).sum(1) / np.where(n > 0, n, np.nan)
            uni = np.where(um, Rm, 0).sum(1) / np.where(um.sum(1) > 0, um.sum(1), np.nan)
            ex = (pick - uni) * 100
            ex[:s17] = np.nan
            ex[T - h:] = np.nan
            o[f"{m}{h}"] = round(float(np.nanmean(ex)), 3)
    return o


def rule(pkv, RKv, rank_lim=80, hold=MAXH):
    rows = []
    for i in range(s17, T - MAXH - 2):
        for j in np.where(pkv[i])[0]:
            m = MKJ[j]
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
    per = lambda d, v: round(float(d[v].mean() / d.days.mean() * 20 * 100), 2) if len(d) else None  # noqa: E731
    yr = YR[a.i.values]
    return {"筆數": len(a), "平均持有": round(float(a.days.mean()), 1), "每20日淨%": per(a, "net"), "每20日超額%": per(a, "exc"),
            "勝率%": round(float((a.net > 0).mean() * 100), 1), "最差5%": round(float(np.percentile(a.net, 5) * 100), 1),
            "上市每20日超額%": per(a[a.m == "上市"], "exc"), "上櫃每20日超額%": per(a[a.m == "上櫃"], "exc"),
            "抱滿60天%": round(float((a.why == "max").mean() * 100), 1),
            "逐年每20日淨%": {int(y): per(a[yr == y], "net") for y in np.unique(yr)},
            "逐年每20日超額%": {int(y): per(a[yr == y], "exc") for y in np.unique(yr)}}


BUY, SELL = 0.0005, 0.0035


def sim(K, pkv, SCv, RKv, rng=None):
    cash, pos, val = 1.0, {}, np.full(T, np.nan)
    for t in range(s17 + 1, T):
        for j in [j for j, p in pos.items() if p[3]]:
            sh, i0, e0, _ = pos.pop(j)
            px = AO[t, j] if not np.isnan(AO[t, j]) else last_close(t - 1, j, e0)
            cash += sh * px * (1 - SELL)
        i = t - 1
        free = K - len(pos)
        if free > 0:
            cand = [j for j in np.where(pkv[i])[0] if j not in pos and not lock[i, j] and not np.isnan(AO[t, j])]
            if rng is None:
                cand.sort(key=lambda j: -SCv[i, j])
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
            elif not RKv[t, j] <= 80:
                p[3] = True
        val[t] = v
    return pd.Series(val[s17 + 1:], index=dates[s17 + 1:]).dropna()


def stat(s):
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    dd = s / s.cummax() - 1
    tr = dd.idxmin()
    pk_ = s.loc[:tr].idxmax()
    back = s.loc[tr:][s.loc[tr:] >= s.loc[pk_]]
    yearly = s.resample("YE").last()
    yearly = (yearly / yearly.shift(1).fillna(s.iloc[0]) - 1) * 100
    return {"年化%": round(((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, 1), "最大回檔%": round(float(dd.min()) * 100, 1),
            "回檔": [f"{pk_.year}/{pk_.month}", f"{tr.year}/{tr.month}", f"{back.index[0].year}/{back.index[0].month}" if len(back) else "還沒回到"],
            "逐年%": {int(k.year): round(float(v), 1) for k, v in yearly.items()}}


taiex = pd.Series({d: v["加權指數"]["close"] for d, v in st["idx"].items() if "加權指數" in (v or {})}).reindex(dates).ffill()
TX = stat(taiex.iloc[s17 + 1:].dropna())
res = {"說明": __doc__, "期間": f"{dates[s17].date()}～{dates[-1].date()}", "加權指數（不含息）": TX, "模型": {}}
say("加權", {k: v for k, v in TX.items() if k != "逐年%"})
MODELS = {"盲測：擴張每年重挑": "擴張每年重挑", "盲測：滾動5年每年重挑": "滾動5年每年重挑", "固定第8版（整段12年挑的）": None}
for name, scheme in MODELS.items():
    if scheme:
        S = wf_score(scheme)
        pkv, RKv = picks_ranks(S)
        SCv = S.values
    else:
        pkv = pk.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)
        RKv, SCv = RK, SC
    o = {"名單超額（核對第一階段）": list_ex(pkv)}
    say(name, o["名單超額（核對第一階段）"])
    o["參考賣法"] = rule(pkv, RKv)
    say("  參考賣法", {k: v for k, v in o["參考賣法"].items() if not isinstance(v, dict)})
    o["帳戶"] = {}
    for K in (3, 5, 10):
        a = stat(sim(K, pkv, SCv, RKv))
        rr = np.array([[stat(sim(K, pkv, SCv, RKv, rng=np.random.default_rng(sd)))[k] for k in ("年化%", "最大回檔%")] for sd in range(100)])
        a["隨機挑100次 年化10/50/90分位"] = [round(float(x), 1) for x in np.percentile(rr[:, 0], [10, 50, 90])]
        a["隨機挑 回檔中位數"] = round(float(np.median(rr[:, 1])), 1)
        a["隨機挑 輸給加權%"] = int(round((rr[:, 0] < TX["年化%"]).mean() * 100))
        o["帳戶"][f"{K}檔每天補"] = a
        say(f"  {K} 檔", {k: v for k, v in a.items() if k != "逐年%"})
    res["模型"][name] = o
    json.dump(res, open("out/wfa_rules.json", "w"), ensure_ascii=False, indent=1)
say("完成")
