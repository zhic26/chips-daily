"""sbl_v8.py 的補充：帳戶模擬比較不受運氣影響的版本（2026-11-09）。
5 檔帳戶照分數挑時，結果很看「剛好挑到哪幾檔」，所以另外算兩種：
  1. 名單全部照參考賣法做（每天把錢平均分給所有持有中的名單股，進場扣 0.4%）：年化、最大回檔、逐年
  2. 5 檔帳戶改成從名單隨機挑，各跑 200 次：年化的 10／50／90 分位、最大回檔中位數
結果存 out/sbl_v8_acct.json"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
DOC = __doc__
t0 = time.time()
src = open("sbl_v8.py", encoding="utf-8").read()
# 只要前面的資料準備和函式（到「各種權重」之前），加上權重設定
head = src[:src.index("res = {\"說明\": DOC")]
exec(head.replace("DOC = __doc__\n", ""))
DOC2 = DOC


def path_portfolio(trs, RKv, rank_lim=80, hold=MAXH):
    """每筆交易每天的報酬（進場日：開盤到收盤；之後收盤到收盤；跌出名次的話最後一天是前一天收盤到當天開盤），每天平均。"""
    ssum = np.zeros(T)
    cnt = np.zeros(T)
    for i, j, m in trs:
        e = i + 1
        px = AO[e, j]
        if np.isnan(px) or np.isnan(AC[i, j]) or lock[i, j]:
            continue
        x, at_open = None, False
        for t in range(e, min(i + hold, T - 2) + 1):
            if np.isnan(AC[t, j]):
                continue
            if rank_lim and not RKv[t, j] <= rank_lim and t < i + hold:
                x, at_open = t + 1, True
                break
        if x is None:
            x = min(i + hold, T - 2)
        prev = px
        for t in range(e, x + 1):
            if t == x and at_open:
                cur = AO[t, j] if not np.isnan(AO[t, j]) else prev
            else:
                cur = AC[t, j] if not np.isnan(AC[t, j]) else prev
            r = cur / prev - 1
            if t == e:
                r -= COST
            ssum[t] += r
            cnt[t] += 1
            prev = cur
    ret = np.where(cnt > 0, ssum / np.where(cnt > 0, cnt, 1), 0.0)
    s = pd.Series(np.cumprod(1 + ret[start + 1:]), index=dates[start + 1:])
    return s, cnt[start + 1:].mean()


def sim_rand(K, pkv, RKv, rng):
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
    s = pd.Series(val[start + 1:], index=dates[start + 1:]).dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return ((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100, (s / s.cummax() - 1).min() * 100


PD = pct(days)
PR = pct(Y3).fillna(0.5)
CONF = {"第7版": (50, 35, 0), "+10": (50, 35, 10), "+15": (50, 35, 15), "+20": (50, 35, 20),
        "網站A 天數40/營收30/大戶15/借券15": (40, 30, 15), "網站B 天數40/營收25/大戶15/借券20": (40, 25, 20)}
NR = 200
res = {"說明": DOC2, "全部名單": {}, "隨機挑5檔": {}}
tx = taiex.iloc[start + 1:].dropna()
res["加權指數（不含息）"] = stat(tx)
# 同市場合格股等權（每天平均），當作「什麼都不挑」的對照
uni = np.zeros(T)
for t in range(start + 1, T):
    rr = []
    for m in ("上市", "上櫃"):
        rr.append(U[m][0][t])
    uni[t] = np.mean(rr)
res["合格股等權（上市上櫃平均，不扣成本）"] = stat(pd.Series(np.cumprod(1 + uni[start + 1:]), index=dates[start + 1:]))
print("加權", res["加權指數（不含息）"], "合格股", res["合格股等權（上市上櫃平均，不扣成本）"], flush=True)
for name, cf in CONF.items():
    S_, pkv = build(*cf)
    RKv = ranks(S_)
    trs = trades_of(pkv)
    s, nopen = path_portfolio(trs, RKv)
    o = stat(s)
    o["平均同時持有檔數"] = round(float(nopen), 1)
    res["全部名單"][name] = o
    print(name, "全部名單", {k: v for k, v in o.items() if k != "逐年%"}, f"[{time.time() - t0:.0f}s]", flush=True)
    rng = np.random.default_rng(7)
    rr = np.array([sim_rand(5, pkv, RKv, rng) for _ in range(NR)])
    res["隨機挑5檔"][name] = {"年化10/50/90分位%": [round(float(x), 1) for x in np.percentile(rr[:, 0], [10, 50, 90])],
                          "最大回檔中位數%": round(float(np.median(rr[:, 1])), 1),
                          "最大回檔10/90分位%": [round(float(x), 1) for x in np.percentile(rr[:, 1], [10, 90])],
                          "輸給加權的比例%": round(float((rr[:, 0] < res["加權指數（不含息）"]["年化%"]).mean() * 100), 1)}
    print(name, "隨機5檔", res["隨機挑5檔"][name], f"[{time.time() - t0:.0f}s]", flush=True)
    del S_, RKv
    gc.collect()
json.dump(res, open("out/sbl_v8_acct.json", "w"), ensure_ascii=False, indent=1)
print("完成", f"[{time.time() - t0:.0f}s]")
