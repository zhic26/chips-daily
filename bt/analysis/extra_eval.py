"""月營收、借券賣出能不能讓名單更好：單一指標 IC，以及加進現行分數後前 20 名的表現。只印精簡表。
用法：python extra_eval.py out/state.pkl ../bt-branch/bt/extra2"""
import glob
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_eval as E  # noqa: E402
import bt_lib as B  # noqa: E402

pd.set_option("display.width", 220)
st = pd.read_pickle(sys.argv[1])
X2 = sys.argv[2]
F, fw, el, mkt = st["F"], st["fw"], st["el"], st["mkt"]
dates = st["P_dates"]
avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)  # noqa: E731
pool = el & (F["instNet"] > 0)
W1 = 10 * pct(F["instNet"] / avg) + 15 * pct(F["inst5d"] / (avg * 5)) + 30 * pct(F["foreignDays"] + 1.5 * F["trustDays"]) \
    + 20 * pct(-F["marginAdd5"].fillna(0) / avg) + 12.5

facs = {}
# ---- 月營收：第 M 月的營收在 M+1 月 11 日以後才算已公布（申報期限是 10 日）----
rp = os.path.join(X2, "revenue.csv")
if os.path.exists(rp):
    rv = pd.read_csv(rp, dtype={"code": str}).drop_duplicates(["ym", "code"])
    rv = rv[rv["code"].isin(F["close"].columns)]
    rev = rv.pivot(index="ym", columns="code", values="rev").sort_index()
    ly = rv.pivot(index="ym", columns="code", values="rev_ly").sort_index()
    yoy = (rev / ly - 1).where(ly > 0) * 100
    yoy3 = (rev.rolling(3).sum() / ly.rolling(3).sum() - 1).where(ly.rolling(3).sum() > 0) * 100
    newhigh = (rev >= rev.shift(1).rolling(11, min_periods=11).max()).astype(float).where(rev.notna())
    avail = pd.to_datetime(rev.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)

    def daily(m):
        m = m.copy()
        m.index = avail
        allidx = m.index.union(dates)
        return m.reindex(allidx).ffill(limit=None).reindex(dates).reindex(columns=F["close"].columns)

    facs["營收年增%"] = daily(yoy)
    facs["近3月營收年增%"] = daily(yoy3)
    facs["營收創12月新高"] = daily(newhigh)
    print("月營收：", rv["ym"].min(), "～", rv["ym"].max(), f"{rv['code'].nunique()} 家")

# ---- 借券賣出（上市）----
parts = sorted(glob.glob(os.path.join(X2, "sbl_part*.json.gz")))
if parts:
    bal = {}
    for p in parts:
        for d, day in json.load(gzip.open(p, "rt")).items():
            if "_err" in day:
                continue
            bal[pd.Timestamp(d)] = {c: v[2] for c, v in day.items() if v[2] is not None}
    bal = pd.DataFrame.from_dict(bal, orient="index").sort_index().reindex(index=dates, columns=F["close"].columns)
    print("借券：", bal.dropna(how="all").index.min().date(), "～", bal.dropna(how="all").index.max().date(), f"{bal.notna().any().sum()} 檔")
    sh = avg * 1000
    facs["借券賣出5日增加/均量"] = (bal - bal.shift(5)) / sh
    facs["借券賣出餘額/均量"] = bal / sh

if not facs:
    sys.exit("沒有資料")

# ---- 1) 單一指標：5 日、20 日的 IC（t 值）----
rows = []
for name, X in facs.items():
    for h in (5, 20):
        for scope, mask in (("合格股", el), ("法人買超池", pool)):
            for m in ("上市", "上櫃"):
                c = mkt.index[mkt == m]
                if X[c].notna().sum().sum() == 0:
                    continue
                ic = E.rowwise_ic(X[c], fw[f"o{h}"][c], mask[c].fillna(False).astype(bool))
                ic = ic[ic.index >= pd.Timestamp("2024-10-01")]
                rows.append({"指標": name, "天": f"{h}日", "範圍": scope, "市場": m, "v": f"{ic.mean():+.3f}({E.tstat(ic.values, h):+.1f})"})
T = pd.DataFrame(rows)
print("\n單一指標 IC（t 值），越正代表數值越大之後越好：")
print(T.pivot_table(index="指標", columns=["天", "範圍", "市場"], values="v", aggfunc="first").to_string())

# ---- 2) 加進分數後，前 20 名的超額 ----
V = {"現行（新權重）": W1}
if "近3月營收年增%" in facs:
    V["＋營收 15 分（近3月年增）"] = W1 * 0.85 + 15 * pct(facs["近3月營收年增%"])
    V["＋營收 15 分（當月年增）"] = W1 * 0.85 + 15 * pct(facs["營收年增%"])
    V["＋創新高加 5 分"] = W1 + 5 * facs["營收創12月新高"].fillna(0)
if "借券賣出5日增加/均量" in facs:
    s5 = facs["借券賣出5日增加/均量"]
    V["借券 5 日大增排除（上市前 10%）"] = W1.where(~(pct(s5) > 0.9))
    V["借券 5 日增加扣 10 分（上市）"] = W1 - 10 * pct(s5).fillna(0.5)
segs = (("前段", "2024-10-01", "2025-09-30"), ("後段", "2025-10-01", "2026-12-31"))
rows = []
for name, sc in V.items():
    pk = B.top_picks(sc.where(el), F, mkt)
    row = {"方式": name}
    for h in (5, 20):
        d = E.picks_daily(pk, fw[f"o{h}"], el, mkt, lock=fw["lockup"])
        for seg, a, b in segs:
            g = d[(d["date"] >= a) & (d["date"] <= b)]
            for m in ("上市", "上櫃"):
                row[f"{h}日{m}{seg}"] = round(g[g["market"] == m]["excess"].mean() * 100, 2)
    rows.append(row)
print("\n前 20 名平均超額（%）：")
print(pd.DataFrame(rows).to_string(index=False))
