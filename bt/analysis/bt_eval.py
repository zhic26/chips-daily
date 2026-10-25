"""回測評估：選股績效、分數分組、單一指標 IC、盤勢分組。"""
import numpy as np
import pandas as pd

MKTS = ("上市", "上櫃")


def cols_of(mkt, m):
    return mkt.index[mkt == m]


def picks_daily(pick, R, elig, mkt, lock=None, cost=0.0):
    """每天每個市場：選出股票的平均報酬、同市場合格股平均報酬、超額、贏過大盤的比例。"""
    rows = []
    for m in MKTS:
        c = cols_of(mkt, m)
        ok = R[c].notna()
        pm = pick[c] & ok
        if lock is not None:
            pm &= ~lock[c].fillna(False).astype(bool)
        um = elig[c] & ok
        pr = R[c].where(pm)
        ur = R[c].where(um).mean(axis=1)
        df = pd.DataFrame({
            "market": m, "n": pm.sum(axis=1), "pick": pr.mean(axis=1) - cost, "univ": ur,
            "beat": pr.gt(ur, axis=0).where(pm).sum(axis=1) / pm.sum(axis=1).replace(0, np.nan),
            "pos": (pr > 0).where(pm).sum(axis=1) / pm.sum(axis=1).replace(0, np.nan),
        })
        df["excess"] = df["pick"] - df["univ"]
        rows.append(df[df["n"] > 0])
    return pd.concat(rows).rename_axis("date").reset_index()


def tstat(x, step=1):
    """非重疊抽樣（每 step 天取一次）的 t 值。"""
    x = pd.Series(x).dropna()
    xs = x.iloc[::step]
    return xs.mean() / (xs.std(ddof=1) / np.sqrt(len(xs))) if len(xs) > 2 and xs.std() > 0 else np.nan


def summarize(daily, h, label=""):
    out = []
    for m, g in list(daily.groupby("market")) + [("合計", daily.groupby("date")[["pick", "univ", "excess", "beat", "pos"]].mean().reset_index())]:
        out.append({"組合": label, "市場": m, "天數": len(g), "選股平均%": g["pick"].mean() * 100,
                    "大盤等權%": g["univ"].mean() * 100, "超額%": g["excess"].mean() * 100,
                    "超額為正的天數%": (g["excess"] > 0).mean() * 100, "個股贏大盤%": g["beat"].mean() * 100,
                    "個股上漲%": g["pos"].mean() * 100, "t值": tstat(g["excess"].values, h)})
    return pd.DataFrame(out)


def rowwise_ic(X, Y, mask, min_n=30):
    """每天的等級相關（Spearman）。"""
    m = mask & X.notna() & Y.notna()
    rx = X.where(m).rank(axis=1)
    ry = Y.where(m).rank(axis=1)
    rx = rx.sub(rx.mean(axis=1), axis=0)
    ry = ry.sub(ry.mean(axis=1), axis=0)
    num = (rx * ry).sum(axis=1)
    den = np.sqrt((rx ** 2).sum(axis=1) * (ry ** 2).sum(axis=1))
    ic = num / den
    return ic.where(m.sum(axis=1) >= min_n)


def factor_table(factors, R, mask, mkt, h, sign=None):
    """每個指標在每個市場的平均 IC、t 值、前 20% 減後 20% 的報酬差（%）。"""
    out = []
    for name, X in factors.items():
        s = (sign or {}).get(name, 1)
        for m in MKTS:
            c = cols_of(mkt, m)
            ic = rowwise_ic(s * X[c], R[c], mask[c])
            q = quint_spread(s * X[c], R[c], mask[c])
            out.append({"指標": name, "市場": m, "IC": ic.mean(), "IC t值": tstat(ic.values, h),
                        "IC>0 天數%": (ic > 0).mean() * 100 if ic.notna().any() else np.nan,
                        "前20%−後20% %": q.mean() * 100, "分差 t值": tstat(q.values, h)})
    return pd.DataFrame(out)


def quint_spread(X, R, mask):
    m = mask & X.notna() & R.notna()
    pr = X.where(m).rank(axis=1, pct=True)
    top = R.where(pr > 0.8).mean(axis=1)
    bot = R.where(pr <= 0.2).mean(axis=1)
    return (top - bot).where(m.sum(axis=1) >= 30)


def bucket_returns(score, R, mask, mkt, nb=10, bench=None):
    """分數分成 nb 組（每天每市場），各組平均超額報酬（%），第 nb 組是最高分。"""
    out = {}
    for m in MKTS:
        c = cols_of(mkt, m)
        mm = mask[c] & score[c].notna() & R[c].notna()
        pr = score[c].where(mm).rank(axis=1, pct=True, method="first")
        b = np.ceil(pr * nb).clip(1, nb)
        ub = R[c].where(bench[c] & R[c].notna()).mean(axis=1) if bench is not None else 0
        ex = R[c].sub(ub, axis=0)
        out[m] = [ex.where(b == k).stack().mean() * 100 for k in range(1, nb + 1)]
    return pd.DataFrame(out, index=[f"第{k}組" for k in range(1, nb + 1)])
