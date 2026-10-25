"""籌碼日報回測：讀每日盤後資料 → 重現網站計分 → 算之後的報酬。"""
import glob
import gzip
import json
import os

import numpy as np
import pandas as pd

LOT = 1000
Q_FIELDS = ["close", "diff", "open", "high", "low", "vol", "amt", "exr"]  # q 陣列的第 2～9 欄


def _open(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") else open(p, encoding="utf-8")


def load(paths, keep_light=False):
    """回傳 dict：各欄位的寬表（列＝日期、欄＝代號）、mkt（代號→上市/上櫃）、name、idx（指數）、flows、market。"""
    cols = {k: {} for k in Q_FIELDS + ["f", "t", "d", "tot", "mbal", "mchg", "sbal", "schg", "dtv"]}
    mkt, name, idx, flows, market, light = {}, {}, {}, {}, {}, {}
    for p in sorted(paths):
        with _open(p) as fh:
            ex = json.load(fh)
        if ex.get("light") and not keep_light:
            continue
        d = pd.Timestamp(ex["date"])
        light[d] = bool(ex.get("light"))
        for k in cols:
            cols[k][d] = {}
        for c, q in ex["q"].items():
            name[c], mkt[c] = q[0], q[1]
            for i, k in enumerate(Q_FIELDS):
                cols[k][d][c] = q[i + 2]
        for c, v in ex.get("inst", {}).items():
            cols["f"][d][c], cols["t"][d][c], cols["d"][d][c], cols["tot"][d][c] = v
        for c, v in ex.get("margin", {}).items():
            cols["mbal"][d][c], cols["mchg"][d][c], cols["sbal"][d][c], cols["schg"][d][c] = v
        for c, v in ex.get("dt", {}).items():
            cols["dtv"][d][c] = v[0]
        idx[d] = ex.get("indices") or {}
        flows[d] = ex.get("flows") or {}
        market[d] = ex.get("market") or {}
    out = {k: pd.DataFrame.from_dict(v, orient="index").sort_index().astype(float) for k, v in cols.items()}
    codes = sorted(set().union(*[set(df.columns) for df in out.values()]))
    dates = out["close"].index
    for k in out:
        out[k] = out[k].reindex(index=dates, columns=codes)
    out["mkt"] = pd.Series(mkt).reindex(codes)
    out["name"] = pd.Series(name).reindex(codes)
    out["idx"], out["flows"], out["market"], out["light"] = idx, flows, market, pd.Series(light)
    return out


def load_exright(extra_dir):
    """證交所除權息參考價：{(日期, 代號): 參考價}。"""
    ref = {}
    for p in sorted(glob.glob(os.path.join(extra_dir, "twt49u_*.json"))):
        j = json.load(open(p, encoding="utf-8"))
        if not isinstance(j, dict) or not j.get("data"):
            continue
        f = j.get("fields") or []
        try:
            i_date = next(i for i, x in enumerate(f) if "日期" in x)
            i_code = next(i for i, x in enumerate(f) if "代號" in x)
            i_ref = next(i for i, x in enumerate(f) if "參考價" in x and "減除" not in x)
        except StopIteration:
            continue
        for r in j["data"]:
            s = str(r[i_date]).strip()
            m = [int(x) for x in s.replace("年", "/").replace("月", "/").replace("日", "").split("/") if x]
            if len(m) != 3:
                continue
            y = m[0] + 1911 if m[0] < 1911 else m[0]
            try:
                v = float(str(r[i_ref]).replace(",", ""))
            except ValueError:
                continue
            ref[(pd.Timestamp(y, m[1], m[2]), str(r[i_code]).strip())] = v
    return ref


def daily_returns(P, exref=None):
    """還原除權息後的每日報酬。證交所除權息日漲跌欄是 0，要用參考價算；櫃買的漲跌已經是對參考價。"""
    close, diff = P["close"], P["diff"]
    prev = close.shift(1)
    r = diff / (close - diff)
    # 漲跌欄缺值（櫃買少數情況）：用前一天收盤價推，太誇張的當成缺值
    fb = close / prev - 1
    r = r.where(diff.notna(), fb.where(fb.abs() < 0.11))
    tw = (P["mkt"] == "上市").astype(bool)
    exr = (P["exr"] == 1)
    if exref:
        s = pd.Series({k: v for k, v in exref.items() if v > 0})
        s.index = pd.MultiIndex.from_tuples(s.index)
        refdf = s[~s.index.duplicated()].unstack().reindex(index=close.index, columns=close.columns)
        r = r.where(refdf.isna(), close / refdf - 1)
        exr = exr & refdf.isna()
    # 證交所除權息日卻查不到參考價：當天報酬視為缺值（不把配息當成下跌）
    r = r.mask(exr & tw, np.nan)
    r = r.where(close.notna())
    return r.clip(-0.5, 0.5)


def forward_returns(P, r, hs=(1, 5, 10, 20)):
    """以選股日 T 為準：隔天開盤買、第 T+h 天收盤賣（可交易報酬）；另附 T 收盤到 T+h 收盤。"""
    L = np.log1p(r.fillna(0)).cumsum()
    g1 = (P["close"] / P["open"] - 1).where(P["open"] > 0)
    out = {}
    for h in hs:
        hold = np.exp(L.shift(-h) - L.shift(-1))  # T+2 ~ T+h 的累積
        out[f"o{h}"] = (1 + g1.shift(-1)) * hold - 1
        out[f"c{h}"] = np.exp(L.shift(-h) - L) - 1
    # 隔天一開盤就漲停鎖住買不到
    lim = (P["open"].shift(-1) >= P["close"] * 1.095) & (P["high"].shift(-1) <= P["open"].shift(-1))
    out["lockup"] = lim
    return out


def features(P, r):
    """網站計分用的原始指標＋額外候選指標（全部以選股日 T 收盤後可得的資料計算）。"""
    vol = P["vol"] / LOT
    nz = (vol > 0).astype(float)
    avg5 = vol.where(vol > 0).rolling(5, min_periods=1).mean()
    tot, f, t, dl = (P[k].fillna(0) / LOT for k in ("tot", "f", "t", "d"))
    F = {"avg5": avg5, "vol": vol, "close": P["close"]}
    F["instNet"], F["foreignNet"], F["trustNet"], F["dealerNet"] = tot, f, t, dl
    F["inst5d"] = tot.rolling(5, min_periods=5).sum()
    F["foreignDays"] = (f > 0).astype(float).rolling(5, min_periods=5).sum()
    F["trustDays"] = (t > 0).astype(float).rolling(5, min_periods=5).sum()
    mchg = P["mchg"]
    F["marginChg"] = mchg
    F["marginBal"] = P["mbal"]
    add5 = mchg.rolling(5, min_periods=5).sum()
    F["marginAdd5"] = add5
    base = P["mbal"] - add5
    F["marginUp5"] = (add5 / base * 100).where(base > 0)
    F["ret20raw"] = (P["close"] / P["close"].shift(20) - 1) * 100
    # 額外候選
    Lr = np.log1p(r.fillna(0)).cumsum()
    for n in (1, 5, 20, 60):
        F[f"ret{n}"] = np.exp(Lr - Lr.shift(n)) - 1
    ma60 = P["close"].rolling(60, min_periods=55).mean()
    F["bias60"] = P["close"] / ma60 - 1
    avg20 = vol.where(vol > 0).rolling(20, min_periods=15).mean()
    F["volSurge"] = vol / avg20
    F["dtRatio"] = (P["dtv"] / P["vol"]).where(P["vol"] > 0)
    F["trust20"] = t.rolling(20, min_periods=20).sum()
    F["foreign20"] = f.rolling(20, min_periods=20).sum()
    F["shortChg"] = P["schg"]
    F["shortRatio"] = (P["sbal"] / P["mbal"]).where(P["mbal"] > 0)
    F["value20"] = (P["amt"].rolling(20, min_periods=15).mean())
    F["streakF"] = _streak(f > 0)
    F["streakT"] = _streak(t > 0)
    F["nzdays"] = nz.rolling(5, min_periods=1).sum()
    return F


def _streak(b):
    """連續為 True 的天數（含當天）。"""
    out = np.zeros(b.shape)
    v = b.values
    for i in range(len(v)):
        out[i] = np.where(v[i], (out[i - 1] if i else 0) + 1, 0)
    return pd.DataFrame(out, index=b.index, columns=b.columns)


def eligible(P, F, min_lots=1000, min_price=10):
    return (F["avg5"] >= min_lots) & (P["close"] >= min_price) & (F["vol"] > 0)


CROWD = {"margin_5d_pct": [10, 20], "margin_min_lots": 300, "runup_20d_pct": [30, 50], "points": [5, 10], "max_penalty": 15}
WEIGHTS = {"inst_today": 25, "inst_5d": 25, "consistency": 10, "big_holders": 25, "margin": 15}


def penalty(F, c=CROWD):
    lo, hi = c["points"]
    mu, add = F["marginUp5"], F["marginAdd5"].fillna(0)
    p1 = np.where(add >= c["margin_min_lots"], np.where(mu >= c["margin_5d_pct"][1], hi, np.where(mu >= c["margin_5d_pct"][0], lo, 0)), 0)
    ru = F["ret20raw"]
    p2 = np.where(ru >= c["runup_20d_pct"][1], hi, np.where(ru >= c["runup_20d_pct"][0], lo, 0))
    p = np.minimum(np.nan_to_num(p1) + np.nan_to_num(p2), c["max_penalty"])
    return pd.DataFrame(p, index=F["avg5"].index, columns=F["avg5"].columns), \
        pd.DataFrame(np.nan_to_num(p1), index=F["avg5"].index, columns=F["avg5"].columns), \
        pd.DataFrame(np.nan_to_num(p2), index=F["avg5"].index, columns=F["avg5"].columns)


def pct_in_market(x, elig, mkt):
    """每天、每個市場內，在合格股票中的百分位（0～1，同分取平均）。"""
    out = pd.DataFrame(np.nan, index=x.index, columns=x.columns)
    for m in ("上市", "上櫃"):
        cols = mkt.index[mkt == m]
        xm = x[cols].where(elig[cols])
        rk = xm.rank(axis=1, method="average")
        n = xm.notna().sum(axis=1)
        out[cols] = rk.sub(1).div((n - 1).replace(0, np.nan), axis=0)
    return out


def site_score(P, F, elig, w=WEIGHTS, big=None, crowd=CROWD):
    """重現網站分數（大戶項：big 為 None 時用中間值，跟網站查不到資料時一樣）。回傳 (分數, 各分項, 扣分)。"""
    mkt = P["mkt"]
    avg = F["avg5"]
    parts = {
        "inst_today": pct_in_market(F["instNet"] / avg, elig, mkt) * w["inst_today"],
        "inst_5d": pct_in_market(F["inst5d"] / (avg * 5), elig, mkt) * w["inst_5d"],
        "consistency": pct_in_market(F["foreignDays"] + 1.5 * F["trustDays"], elig, mkt) * w["consistency"],
        "margin": pct_in_market(-F["marginChg"].fillna(0) / avg, elig, mkt) * w["margin"],
    }
    if big is None:
        parts["big_holders"] = pd.DataFrame(0.5 * w["big_holders"], index=avg.index, columns=avg.columns)
    else:
        parts["big_holders"] = ((big.fillna(0) + 1) / 2).clip(0, 1) * w["big_holders"]
    pen = penalty(F, crowd)[0]
    raw = sum(parts.values())
    score = (raw - pen).clip(lower=0).where(elig)
    return score, parts, pen


def top_picks(score, F, mkt, n=20, pool_mask=None):
    """每天每個市場取前 n 名（同分比法人買超）。回傳布林寬表。"""
    pool = F["instNet"] > 0 if pool_mask is None else pool_mask
    s = score.where(pool) + F["instNet"].clip(lower=0) * 1e-9  # 同分時法人買超大的優先
    pick = pd.DataFrame(False, index=s.index, columns=s.columns)
    for m in ("上市", "上櫃"):
        cols = mkt.index[mkt == m]
        rk = s[cols].rank(axis=1, ascending=False, method="first")
        pick[cols] = rk <= n
    return pick
