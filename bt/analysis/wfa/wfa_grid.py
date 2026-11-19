"""逐年盲測（Walk-Forward Analysis）：網站「挑權重的方法」離開挑權重用的資料之後還剩多少（2026-11-19，使用者要求）。

起因：網站上第 8 版的 12 年數字（名單 20 日超額上市 0.90%、上櫃 0.85%），權重是用同一段 12 年挑的、再用同一段算，
等於自己印考卷自己改。這裡改成「滾動式裸考」：每次只准用之前的資料挑權重，挑完鎖死，拿去跑之後沒看過的期間，
一路往後滾，最後把每一段盲測成績拼起來。

做法（算法同 weights_full.py、sbl_v8.py，也就是網站的 12 年回測）：
- 六項分數：法人今日買超、5 日累計、法人買超天數、融資 5 日減少、近 3 月營收年增、借券賣出餘額（越少越高）。
  千張大戶沒有 12 年的歷史資料，跟之前一樣不算。
- 權重 10 分一格、六項加起來 100 分，共 3003 組；另外放第 6、7、8 版的權重當對照。
- 每組每天照網站規則挑上市、上櫃各 20 檔（當天法人合計買超、同分比法人買超），隔天開盤買、開盤鎖漲停不算，
  算 5／20 日後比同市場合格股（等權）多多少。目標＝上市、上櫃 20 日超額的平均（網站兩個市場用同一組權重）。
- 盲測：訓練資料的最後 30 天不用（20 日報酬會偷看到測試期）。四種滾法：
  擴張（之前全部）每年重挑、滾動 3 年每年重挑、滾動 5 年每年重挑、擴張每半年重挑。測試期 2017～2026/10。
- 對照：固定第 6／7／8 版（第 7、8 版是用整段 12 年挑的，2017 以後對它們不算樣本外）、事後最好的一組、3003 組的中位數。
- 檢查：第 8 版 12 年要重現 0.90／0.85；只用五項（借券固定 0）的擴張盲測要重現 weights_full 的 0.52%（逐年平均）。
結果：out/wfa_grid.json、out/wfa_grid.npz（每組每天的超額，第二階段 wfa_rules.py 會讀挑到的權重）。"""
import itertools
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


KEYS = ["今日", "5日", "天數", "融資", "營收", "借券"]
MARKETS = ("上市", "上櫃")
MI = {m: np.array([cix[c] for c in mkt.index[mkt == m] if c in cix]) for m in MARKETS}
elv_np = el.reindex(index=dates, columns=cols).fillna(False).values.astype(bool)

A = [pct(tot / avg), pct(inst5d / (avg * 5)), pct(days), pct(-madd5.fillna(0) / avg), pct(Y3).fillna(0.5), GOOD]
A = [a.reindex(index=dates, columns=cols).values for a in A]
totv = tot.reindex(index=dates, columns=cols).fillna(0).values
pool = elv_np & (totv > 0)
tb = np.clip(totv, 0, None) * 1e-9  # 同分時法人買超大的優先（同 bt_lib.top_picks）
lockb = lock.astype(bool)
adjv = adj.values
g1 = (C / O - 1).where(O > 0).values
FW = {}
for h in (5, 20):
    R = np.full(adjv.shape, np.nan)
    R[:T - h] = (1 + g1[1:T - h + 1]) * adjv[h:T] / adjv[1:T - h + 1] - 1
    FW[h] = R
SL = {}
for m in MARKETS:
    ci = MI[m]
    uni = {}
    for h in (5, 20):
        Rm = FW[h][:, ci]
        um = elv_np[:, ci] & ~np.isnan(Rm)
        uni[h] = np.where(um, Rm, 0).sum(axis=1) / np.where(um.sum(axis=1) > 0, um.sum(axis=1), np.nan)
    SL[m] = {"A": [np.ascontiguousarray(a[:, ci]) for a in A], "pool": pool[:, ci], "tb": tb[:, ci], "lock": lockb[:, ci],
             "R": {h: np.ascontiguousarray(FW[h][:, ci]) for h in (5, 20)}, "uni": uni}
del A, FW
gc.collect()
say("準備完成")


def run(w):
    """回傳 [h(5,20), 市場, 日] 的超額（%）；沒有名單或報酬還沒出來的日子是 NaN。"""
    out = np.full((2, 2, T), np.nan, dtype=np.float32)
    for mi, m in enumerate(MARKETS):
        s = SL[m]
        S = s["tb"].copy()
        for wk, a in zip(w, s["A"]):
            if wk:
                S += wk * a
        S = np.where(s["pool"] & ~np.isnan(S), S, -np.inf)
        idx = np.argpartition(-S, 19, axis=1)[:, :20]
        valid = np.take_along_axis(S, idx, axis=1) > -np.inf
        lk = np.take_along_axis(s["lock"], idx, axis=1)
        for hi, h in enumerate((5, 20)):
            vals = np.take_along_axis(s["R"][h], idx, axis=1)
            ok = valid & ~lk & ~np.isnan(vals)
            n = ok.sum(axis=1)
            mean = np.where(n > 0, np.where(ok, vals, 0).sum(axis=1) / np.maximum(n, 1), np.nan)
            ex = (mean - s["uni"][h]) * 100
            ex[:start] = np.nan
            ex[T - h:] = np.nan
            out[hi, mi] = ex
    return out


CAND = {"第6版": (10, 10, 30, 15, 20, 0), "第7版": (0, 0, 50, 0, 35, 0), "第8版": (0, 0, 40, 0, 30, 15)}
grid = [w for w in itertools.product(range(0, 101, 10), repeat=6) if sum(w) == 100]
if os.environ.get("QUICK"):  # 測流程用：只跑一小部分
    grid = grid[::50]
allw = list(CAND.values()) + grid
E = np.full((len(allw), 2, 2, T), np.nan, dtype=np.float32)
for i, w in enumerate(allw):
    E[i] = run(w)
    if i == 2:
        say("第 8 版 12 年 20 日（應重現 上市 0.90、上櫃 0.85）", [round(float(np.nanmean(E[2, 1, mi])), 3) for mi in range(2)],
            "第 7 版（0.76、0.70）", [round(float(np.nanmean(E[1, 1, mi])), 3) for mi in range(2)])
    if i % 250 == 0:
        say(i, "/", len(allw))
np.savez_compressed("out/wfa_grid.npz", E=E, w=np.array(allw), dates=dates.values.astype("datetime64[D]").astype(str))
say("格點跑完")

dn = dates.values
yr = pd.DatetimeIndex(dates).year.values
nC = len(CAND)
G = E[nC:]
gw = np.array(grid)
D30 = np.timedelta64(30, "D")
TEST0 = np.datetime64("2017-01-01")
r3 = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 3)  # noqa: E731


def obj(mask):
    """每組在 mask 期間的目標（上市、上櫃 20 日超額的平均，每天先平均再對天數平均）。"""
    return np.nanmean(G[:, 1][..., mask], axis=-1).mean(axis=1)


def periods(kind):
    out = []
    if kind == "half":
        for y in range(2017, 2027):
            for s0, s1 in ((f"{y}-01-01", f"{y}-07-01"), (f"{y}-07-01", f"{y + 1}-01-01")):
                out.append((np.datetime64(s0), np.datetime64(s1)))
    else:
        out = [(np.datetime64(f"{y}-01-01"), np.datetime64(f"{y + 1}-01-01")) for y in range(2017, 2027)]
    return [(a, b) for a, b in out if (dn >= a).any() and np.isfinite(np.nanmean(G[0, 1, 0][(dn >= a) & (dn < b)]))]


def walk(kind, years_back=None, sub=None):
    """回傳 (拼起來的每天超額 [h, 市場, 日]、每段挑到的權重與成績)。sub：只在這些組裡挑（檢查用）。"""
    Gs = G if sub is None else G[sub]
    gws = gw if sub is None else gw[sub]
    stitched = np.full((2, 2, T), np.nan, dtype=np.float32)
    rows = []
    for a, b in periods(kind):
        hi = a - D30
        lo = dates.values[start] if years_back is None else a - np.timedelta64(365 * years_back, "D") - D30
        trm = (dn >= lo) & (dn < hi)
        tem = (dn >= a) & (dn < b)
        o_tr = np.nanmean(Gs[:, 1][..., trm], axis=-1).mean(axis=1)
        k = int(np.nanargmax(o_tr))
        stitched[..., tem] = Gs[k][..., tem]
        o_te_all = np.nanmean(Gs[:, 1][..., tem], axis=-1).mean(axis=1)
        v8 = float(np.nanmean(E[2, 1][..., tem], axis=-1).mean())
        rows.append({"測試期": f"{str(a)[:7]}～{str(b - np.timedelta64(1, 'D'))[:7]}",
                     "挑到的權重": dict(zip(KEYS, map(int, gws[k]))), "訓練期成績": r3(o_tr[k]), "測試期成績": r3(o_te_all[k]),
                     "第8版同期": r3(v8), "在全部組裡排前%": r3((o_te_all > o_te_all[k]).mean() * 100),
                     "全部組中位數": r3(np.nanmedian(o_te_all))})
    return stitched, rows


def summarize(X, mask=None):
    """X [h, 市場, 日]：2017 起（或 mask）每個市場 5／20 日平均、兩市場平均、逐年。"""
    m_ = (dn >= TEST0) if mask is None else mask
    o = {}
    for hi, h in enumerate((5, 20)):
        for mi, mk in enumerate(MARKETS):
            o[f"{mk}{h}"] = r3(np.nanmean(X[hi, mi][m_]))
    o["兩市場20"] = r3((o["上市20"] + o["上櫃20"]) / 2)
    both = np.nanmean(X[1], axis=0)
    o["逐年20（兩市場平均）"] = {int(y): r3(np.nanmean(both[(yr == y) & m_])) for y in range(2017, 2027) if ((yr == y) & m_).any()}
    return o


def block_boot(x, L=250, nb=2000, seed=0):
    x = x[np.isfinite(x)]
    n = len(x)
    rng = np.random.default_rng(seed)
    k = int(np.ceil(n / L))
    ms = np.empty(nb)
    for i_ in range(nb):
        s0 = rng.integers(0, n, k)
        idx = ((s0[:, None] + np.arange(L)[None, :]).ravel()[:n]) % n
        ms[i_] = x[idx].mean()
    return [r3(v) for v in np.percentile(ms, [5, 50, 95])], r3((ms <= 0).mean() * 100)


res = {"說明": __doc__, "資料": f"{dates[start].date()}～{dates[-1].date()}，{T} 個交易日；測試期 2017/1～{dates[-21].date()}（20 日報酬要等 20 天）",
       "組數": len(grid), "固定權重": {}, "盲測": {}, "檢查": {}}
for (name, w), Xi in zip(CAND.items(), E[:nC]):
    res["固定權重"][name] = {"權重": dict(zip(KEYS, w)), "12年": summarize(Xi, dn >= dates.values[start]), "2017以後": summarize(Xi)}
test = dn >= TEST0
o_test = obj(test)
kb = int(np.nanargmax(o_test))
res["固定權重"]["事後最好的一組（偷看答案）"] = {"權重": dict(zip(KEYS, map(int, gw[kb]))), "2017以後": summarize(G[kb])}
res["固定權重"]["3003組中位數（2017以後）"] = r3(np.nanmedian(o_test))
res["固定權重"]["3003組前10%門檻（2017以後）"] = r3(np.nanpercentile(o_test, 90))

SCHEMES = {"擴張每年重挑": ("year", None), "滾動3年每年重挑": ("year", 3), "滾動5年每年重挑": ("year", 5), "擴張每半年重挑": ("half", None)}
ST = {}
for nm, (kind, yb) in SCHEMES.items():
    X, rows = walk(kind, yb)
    ST[nm] = X
    s = summarize(X)
    s["在3003組裡排前%（2017以後整段）"] = r3((o_test > s["兩市場20"]).mean() * 100)
    both = np.nanmean(X[1], axis=0)[test]
    s["區塊拔靴法 90%區間、平均≤0的機率%"] = block_boot(both)
    s["每段"] = rows
    s["挑到的權重平均"] = {k: r3(np.mean([r["挑到的權重"][k] for r in rows])) for k in KEYS}
    res["盲測"][nm] = s
    say(nm, {k: v for k, v in s.items() if k not in ("每段", "逐年20（兩市場平均）")})

# 檢查：五項（借券固定 0）擴張每年重挑，逐年平均要接近 weights_full 的 0.52%
sub5 = np.where(gw[:, 5] == 0)[0]
X5, rows5 = walk("year", None, sub5)
yv = [r["測試期成績"] for r in rows5]
res["檢查"]["五項擴張盲測逐年平均（應接近 weights_full 0.52%）"] = r3(np.mean(yv))
res["檢查"]["五項擴張盲測挑到的權重"] = {r["測試期"]: r["挑到的權重"] for r in rows5}
res["檢查"]["五項擴張盲測（每天平均）"] = summarize(X5)
v6y = [r3(np.nanmean(E[0, 1][..., (dn >= np.datetime64(f"{y}-01-01")) & (dn < np.datetime64(f"{y + 1}-01-01"))], axis=-1).mean()) for y in range(2017, 2027)]
res["檢查"]["第6版逐年平均（weights_full 是 0.35%）"] = r3(np.mean(v6y))
say("檢查", res["檢查"]["五項擴張盲測逐年平均（應接近 weights_full 0.52%）"], res["檢查"]["第6版逐年平均（weights_full 是 0.35%）"])

# 每天的差異（盲測－第 8 版固定）有多穩
d_ = np.nanmean(ST["擴張每年重挑"][1], axis=0)[test] - np.nanmean(E[2, 1], axis=0)[test]
res["盲測"]["擴張每年重挑"]["減第8版固定：每天差異平均、區塊拔靴法"] = [r3(np.nanmean(d_)), block_boot(d_)]
np.savez_compressed("out/wfa_stitched.npz", **{k: v for k, v in ST.items()})
json.dump(res, open("out/wfa_grid.json", "w"), ensure_ascii=False, indent=1)
say("完成")
