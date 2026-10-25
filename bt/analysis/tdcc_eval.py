"""集保（千張大戶、股東人數）因子的回測：只在每天的候選股（扣大戶項前分數前 K 名）裡比較。
用法：python tdcc_eval.py out/state.pkl candidates.csv tdcc資料夾"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_eval as E  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
st = pd.read_pickle(sys.argv[1])
cand = pd.read_csv(sys.argv[2], dtype={"code": str, "week": str, "prev": str})
tab = {}
for p in glob.glob(os.path.join(sys.argv[3], "part*.jsonl")):
    for ln in open(p):
        x = json.loads(ln)
        tab[(x["c"], x["w"])] = {int(k): v for k, v in x["t"].items()}
print("集保資料筆數", len(tab))


def feats(t):
    if not t:
        return None
    lv = {k: v for k, v in t.items() if 1 <= k <= 15}
    total = t[max(t)]  # 最後一列是合計
    return {"big15": lv.get(15, [0, 0, 0])[2], "big400": sum(lv.get(k, [0, 0, 0])[2] for k in (12, 13, 14, 15)),
            "small50": sum(lv.get(k, [0, 0, 0])[2] for k in range(1, 9)), "holders": total[0],
            "big15n": lv.get(15, [0, 0, 0])[0]}


rows = []
for d, c, w, wp in cand.itertuples(index=False):
    a, b = feats(tab.get((c, w))), feats(tab.get((c, wp)))
    if not a or not b:
        continue
    rows.append({"date": pd.Timestamp(d), "code": c, "bigChg": a["big15"] - b["big15"], "big400Chg": a["big400"] - b["big400"],
                 "smallChg": a["small50"] - b["small50"],
                 "holdersChg": (a["holders"] / b["holders"] - 1) * 100 if b["holders"] else np.nan,
                 "big15": a["big15"]})
X = pd.DataFrame(rows)
print("有集保資料的候選股-日：", len(X), "／", len(cand))

fw, el, mkt, score = st["fw"], st["el"], st["mkt"], st["score"]
for h in (5, 10, 20):
    R = fw[f"o{h}"]
    u = {}
    for m in ("上市", "上櫃"):
        cc = mkt.index[mkt == m]
        u[m] = R[cc].where(el[cc] & R[cc].notna()).mean(axis=1)
    X[f"ex{h}"] = [R.at[d, c] - u[mkt[c]].get(d, np.nan) if c in R.columns else np.nan for d, c in zip(X["date"], X["code"])]
X["market"] = X["code"].map(mkt)
X["score0"] = [score.at[d, c] for d, c in zip(X["date"], X["code"])]

# 1) 單一集保指標：每天候選股內排名，前 1/3 減後 1/3 的超額差（%），以及等級相關
print("\n=== 候選股內：集保指標前 1/3 − 後 1/3 的超額報酬差（%）===")
out = []
for f, sgn in (("bigChg", 1), ("big400Chg", 1), ("holdersChg", -1), ("smallChg", -1)):
    for h in (5, 10, 20):
        diffs, ics = [], []
        for (d, m), g in X.dropna(subset=[f, f"ex{h}"]).groupby(["date", "market"]):
            if len(g) < 15:
                continue
            rk = (sgn * g[f]).rank(pct=True)
            diffs.append(g.loc[rk > 2 / 3, f"ex{h}"].mean() - g.loc[rk <= 1 / 3, f"ex{h}"].mean())
            ics.append(g[f].mul(sgn).rank().corr(g[f"ex{h}"].rank()))
        out.append({"指標": f + ("（越少越好）" if sgn < 0 else ""), "天數": f"{h}日", "前1/3−後1/3%": np.nanmean(diffs) * 100,
                    "t值": E.tstat(np.array(diffs), h), "IC": np.nanmean(ics)})
print(pd.DataFrame(out).to_string(index=False))

# 2) 網站規則：大戶項用真的集保資料 vs 一律給中間值，各取前 20 名
print("\n=== 網站前 20 名：大戶項用真實資料 vs 中間值（集保資料期間）===")
X["bigPart"] = ((X["bigChg"].fillna(0) + 1) / 2).clip(0, 1) * 25
X["score_real"] = X["score0"] - 12.5 + X["bigPart"]
res = []
for lab, col in (("大戶項＝中間值", "score0"), ("大戶項＝真實資料", "score_real")):
    for h in (5, 10, 20):
        v = []
        for (d, m), g in X.groupby(["date", "market"]):
            top = g.sort_values(col, ascending=False).head(20)
            v.append(top[f"ex{h}"].mean())
        v = pd.Series(v).dropna()
        res.append({"版本": lab, "天數": f"{h}日", "平均超額%": v.mean() * 100, "t值": E.tstat(v.values, h)})
print(pd.DataFrame(res).pivot(index="版本", columns="天數", values=["平均超額%", "t值"]).to_string())
X.to_csv(os.path.join(os.path.dirname(sys.argv[1]), "tdcc_features.csv"), index=False)
