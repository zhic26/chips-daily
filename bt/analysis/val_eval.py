"""估值（本益比、股價淨值比、殖利率）與獲利（ROE＝淨值比÷本益比）能不能讓名單更好。只印精簡表。
用法：python val_eval.py"""
import glob, gzip, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B  # noqa: E402

st = pd.read_pickle("out/state.pkl")
F, fw, el, mkt = st["F"], st["fw"], st["el"], st["mkt"]; dates = st["P_dates"]; avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)  # noqa: E731
cols = F["close"].columns
V = "../bt-branch/bt/val/"
pe, pb, yl = (pd.DataFrame(np.nan, index=dates, columns=cols) for _ in range(3))
for m in ("twse", "tpex"):
    for f in sorted(glob.glob(V + m + "/*.json.gz")):
        d = pd.Timestamp(os.path.basename(f)[:10])
        if d not in pe.index:
            continue
        rows = json.load(gzip.open(f, "rt"))
        cc = [c for c in rows if c in pe.columns]
        a = np.array([[np.nan if x is None else x for x in rows[c]] for c in cc], dtype=float)
        pe.loc[d, cc], pb.loc[d, cc], yl.loc[d, cc] = a[:, 0], a[:, 1], a[:, 2]
have = pb.notna().sum(axis=1)
print("估值資料：", have[have > 0].index.min().date(), "～", have[have > 0].index.max().date(), "，平均每天", int(have[have > 0].mean()), "檔")
# 本益比空白多半是虧損：盈餘殖利率給 −0.05（比任何獲利公司都低）
ep = (1 / pe).where(pe > 0)
ep = ep.where(ep.notna() | pb.isna(), -0.05)
bp = (1 / pb).where(pb > 0)
roe = (pb / pe).where(pe > 0) * 100
roe = roe.where(roe.notna() | pb.isna(), -5)
facs = {"盈餘殖利率（1/本益比）": ep, "淨值比倒數（1/PB）": bp, "殖利率": yl, "ROE（PB÷PE）": roe}

rv = pd.read_csv("../bt-branch/bt/extra2/revenue.csv", dtype={"code": str}).drop_duplicates(["ym", "code"])
rev = rv.pivot(index="ym", columns="code", values="rev").sort_index(); ly = rv.pivot(index="ym", columns="code", values="rev_ly").sort_index()
y3 = (rev.rolling(3).sum() / ly.rolling(3).sum() - 1).where(ly.rolling(3).sum() > 0) * 100
y3.index = pd.to_datetime(y3.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)
Y3 = y3.reindex(y3.index.union(dates)).ffill().reindex(dates).reindex(columns=cols)
W0 = 10 * pct(F["instNet"] / avg) + 10 * pct(F["inst5d"] / (avg * 5)) + 30 * pct(F["foreignDays"] + 1.5 * F["trustDays"]) \
    + 15 * pct(-F["marginAdd5"].fillna(0) / avg) + 20 * pct(Y3).fillna(0.5)
inr = pd.Series(dates >= pd.Timestamp("2024-10-01"), index=dates)
elr = el.where(inr, axis=0).fillna(False).astype(bool)
pool = el & (F["instNet"] > 0)

# 1) 單一指標 IC
rows = []
for name, X in facs.items():
    for h in (5, 20):
        for scope, mask in (("合格股", el), ("法人買超池", pool)):
            row = {"指標": name, "持有": f"{h}日", "範圍": scope}
            for m in ("上市", "上櫃"):
                c = mkt.index[mkt == m]
                ic = E.rowwise_ic(X[c], fw[f"o{h}"][c], mask[c].fillna(False).astype(bool))
                ic = ic[ic.index >= pd.Timestamp("2024-10-01")]
                row[m] = f"{ic.mean():+.3f}({E.tstat(ic.values, h):+.1f})"
            rows.append(row)
print("\n單一指標 IC（t 值）：越正代表數值越大之後越好")
print(pd.DataFrame(rows).to_string(index=False))

# 2) 加進分數
P = {k: pct(v).fillna(0.5) for k, v in facs.items()}
val = (P["盈餘殖利率（1/本益比）"] + P["淨值比倒數（1/PB）"] + P["殖利率"]) / 3
VAR = {
    "現行": W0,
    "＋盈餘殖利率 10 分": W0 + 10 * P["盈餘殖利率（1/本益比）"],
    "＋淨值比倒數 10 分": W0 + 10 * P["淨值比倒數（1/PB）"],
    "＋殖利率 10 分": W0 + 10 * P["殖利率"],
    "＋價值綜合 10 分": W0 + 10 * val,
    "＋價值綜合 20 分": W0 + 20 * val,
    "＋ROE 10 分": W0 + 10 * P["ROE（PB÷PE）"],
    "＋ROE 10、價值綜合 10": W0 + 10 * P["ROE（PB÷PE）"] + 10 * val,
}
GATE = {"虧損股不入選": (pe > 0) | pb.isna(), "本益比 > 60 不入選": ~(pe > 60)}
res = []


def evaluate(name, sc, gate=None):
    pm = pool if gate is None else pool & gate
    pk = B.top_picks(sc.where(el), F, mkt, pool_mask=pm).where(inr, axis=0).fillna(False).astype(bool)
    row = {"方式": name}
    for h in (5, 20):
        d = E.picks_daily(pk, fw[f"o{h}"], elr, mkt, lock=fw["lockup"])
        s = E.summarize(d, h).set_index("市場")
        for m in ("上市", "上櫃"):
            row[f"{h}日{m}"] = round(s.loc[m, "超額%"], 2)
        row[f"{h}日t"] = round(s.loc["合計", "t值"], 1)
        late = d[d["date"] >= "2025-10-01"].groupby("date")["excess"].mean()
        early = d[d["date"] < "2025-10-01"].groupby("date")["excess"].mean()
        row[f"{h}日前段"], row[f"{h}日後段"] = round(early.mean() * 100, 2), round(late.mean() * 100, 2)
    res.append(row)


for name, sc in VAR.items():
    evaluate(name, sc)
for name, g in GATE.items():
    evaluate(name, W0, g)
print("\n前 20 名平均超額（%）。t：上市櫃合計、不重疊抽樣。前段：2024/10～2025/9，後段：2025/10 以後")
print(pd.DataFrame(res).to_string(index=False))
