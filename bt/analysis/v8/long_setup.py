"""長期回測的共用資料準備（取代 price_rules.py 前半段，直接從原始日資料算，不用 state.pkl）。
分數＝第 8 版不含千張大戶：法人買超天數 40、近 3 月營收年增 30、借券賣出餘額 15（越少越高分；法人今日、5 日累計、融資 5 日減少都是 0 分）。
環境變數 BT_START：從哪天開始挑名單（預設 2014-03-03）。"""
import gc
import glob
import json
import os

import numpy as np
import pandas as pd

import bt_lib as B

RAW, EXTRA, X2 = "../bt-branch/bt/raw", "../bt-branch/bt/extra", "../bt-branch/bt/extra2"
P = B.load(glob.glob(f"{RAW}/*.json.gz"))
# 2018/1/12 以前的櫃買法人（舊格式另外抓的）補進去；原本就有的優先
side = {pd.Timestamp(os.path.basename(p)[:10]): json.load(open(p)) for p in glob.glob("../bt-branch/bt/tpex_inst_old/*.json")}
side = {d: m for d, m in side.items() if m and d in P["close"].index}
if side:
    for i, k in ((0, "f"), (1, "t"), (3, "tot")):
        df = pd.DataFrame({d: {c: v[i] for c, v in m.items()} for d, m in side.items()}).T
        P[k] = P[k].combine_first(df.reindex(index=P[k].index, columns=P[k].columns))
    print(f"櫃買法人舊格式補了 {len(side)} 天", flush=True)
for k in ("sbal", "schg", "dtv", "d", "amt"):
    P.pop(k, None)
gc.collect()
dates = P["close"].index
cols = P["close"].columns
mkt = P["mkt"]
st = {"idx": P["idx"]}
r = B.daily_returns(P, B.load_exright(EXTRA))

LOT = B.LOT
vol = P["vol"] / LOT
avg = vol.where(vol > 0).rolling(5, min_periods=1).mean()
tot, f, t_ = (P[k].fillna(0) / LOT for k in ("tot", "f", "t"))
inst5d = tot.rolling(5, min_periods=5).sum()
days = (f > 0).astype(float).rolling(5, min_periods=5).sum() + 1.5 * (t_ > 0).astype(float).rolling(5, min_periods=5).sum()
madd5 = P["mchg"].rolling(5, min_periods=5).sum()
el = (avg >= 1000) & (P["close"] >= 10) & (vol > 0)
del f, t_
gc.collect()

# 隔天一開盤就鎖漲停買不到：2015/6/1 以前漲跌幅是 7%，之後 10%
thr = pd.Series(np.where(dates < pd.Timestamp("2015-06-01"), 1.065, 1.095), index=dates).shift(-1).fillna(1.095)
lockdf = (P["open"].shift(-1).ge(P["close"].mul(thr, axis=0))) & (P["high"].shift(-1) <= P["open"].shift(-1))

pct = lambda X: B.pct_in_market(X, el, mkt)  # noqa: E731
rv = pd.concat([pd.read_csv(p, dtype={"code": str}) for p in (f"{X2}/revenue_old.csv", f"{X2}/revenue.csv") if os.path.exists(p)])
rv = rv.drop_duplicates(["ym", "code"])
rev = rv.pivot(index="ym", columns="code", values="rev").sort_index()
ly = rv.pivot(index="ym", columns="code", values="rev_ly").sort_index()
y3 = (rev.rolling(3).sum() / ly.rolling(3).sum() - 1).where(ly.rolling(3).sum() > 0) * 100
y3.index = pd.to_datetime(y3.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)  # 次月 11 日起才用
Y3 = y3.reindex(y3.index.union(dates)).ffill().reindex(dates).reindex(columns=cols)
# 借券賣出餘額（bt/sbl 每天的證交所 TWT93U、櫃買中心借券；第 13 欄「當日餘額」，股 → 張），÷ 5 日均量，同市場合格股排百分位，越少越高分；不能借券賣出的給中間值
import gzip as _gz
_SB = np.full((len(dates), len(cols)), np.nan)
_ci = {k: j for j, k in enumerate(cols)}
for _t, _d in enumerate(dates):
    for _mk in ("twse", "tpex"):
        _p = f"../bt-branch/bt/sbl/{_mk}/{_d.date()}.json.gz"
        if not os.path.exists(_p):
            continue
        with _gz.open(_p, "rt", encoding="utf-8") as _fh:
            _j = json.load(_fh)
        _f = _j.get("fields") or []
        if len(_f) <= 12 or "當日餘額" not in _f[12]:
            continue
        for _c, _r in (_j.get("rows") or {}).items():
            _jj = _ci.get(_c)
            if _jj is not None and len(_r) > 10 and _r[10] is not None:
                _SB[_t, _jj] = _r[10] / 1000
_av = avg.reindex(index=dates, columns=cols).values
SBL = pd.DataFrame(np.where(_av > 0, _SB / np.where(_av > 0, _av, 1), np.nan), index=dates, columns=cols)
GOOD = (1 - pct(SBL)).fillna(0.5)
print(f"借券：{int((~np.isnan(_SB)).any(axis=1).sum())} 天有資料", flush=True)
del _SB, _av
W0 = 40 * pct(days) + 30 * pct(Y3).fillna(0.5) + 15 * GOOD  # 第 8 版（2026-11-10）：法人買超天數 40、營收 30、借券 15；千張大戶 15 沒有那麼久的歷史資料，不算
pk = B.top_picks(W0.where(el), {"instNet": tot}, mkt)
RK = pd.DataFrame(np.nan, index=dates, columns=cols)
for m in ("上市", "上櫃"):
    c = mkt.index[mkt == m]
    RK[c] = W0[c].where(el[c]).rank(axis=1, ascending=False, method="first")
RK = RK.values
SC = W0.values
lock = lockdf.reindex(index=dates, columns=cols).fillna(False).values

O, H, L, C = (P[k] for k in ("open", "high", "low", "close"))
adj = (1 + r.fillna(0)).cumprod()
fac = adj / C
AO, AH, AL, AC = (O * fac).values, (H * fac).values, (L * fac).values, adj.where(C.notna()).values
T = len(dates)
COST = 0.004
start = int(np.searchsorted(dates.values, np.datetime64(os.environ.get("BT_START", "2014-03-03"))))
cix = {k: j for j, k in enumerate(cols)}

elv = el.fillna(False).astype(bool)
intra = pd.DataFrame(AC / AO - 1, index=dates, columns=cols)
pc = np.vstack([np.full((1, AC.shape[1]), np.nan), AC[:-1]])
gapd = pd.DataFrame(AO / pc - 1, index=dates, columns=cols)
U = {}
for m in ("上市", "上櫃"):
    c = mkt.index[mkt == m]
    prev = elv[c].shift(1).fillna(False).astype(bool)
    U[m] = (r[c].where(prev).mean(axis=1).fillna(0).values, intra[c].where(prev).mean(axis=1).fillna(0).values,
            gapd[c].where(prev).mean(axis=1).fillna(0).values)
del intra, gapd, pc
gc.collect()


def bench(m, e, x, at_open):
    """同市場合格股等權：e 天開盤買、x 天（at_open 時是開盤）賣。"""
    ur, ui, ug = U[m]
    v = 1 + ui[e]
    for t in range(e + 1, x):
        v *= 1 + ur[t]
    v *= (1 + ug[x]) if at_open else (1 + ur[x] if x > e else 1)
    return v - 1


def last_close(x, j, lo):
    while x > lo and np.isnan(AC[x, j]):
        x -= 1
    return AC[x, j]


MAXH = 60
trades = [(i, cix[code], mkt[code]) for i in range(start, T - MAXH - 2) for code in cols[pk.iloc[i].values]]
print("資料", dates[0].date(), "～", dates[-1].date(), f"{T} 天、{len(cols)} 檔；名單交易 {len(trades)} 筆（名單日期 {dates[start].date()}～{dates[T - MAXH - 3].date()}）", flush=True)
