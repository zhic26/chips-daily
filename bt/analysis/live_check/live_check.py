"""網站實盤（2026/10/27 起）為什麼輸：跟 12 年回測比雜訊有多大、盤勢不好時名單本來就比較差嗎、哪一項分數在跌勢裡撐得住。
（2026-11-28 使用者問「為何都是輸的、要不要新增或調整權重」）
做法：用 wfa_grid.py 同一套 12 年回測（每天上市、上櫃各挑 20 檔，隔天開盤買、鎖漲停不算，5／20 日後比同市場合格股等權，不扣成本），
算第 6／7／8 版和六項單一分數每天的超額；盤勢用當天（名單公布日）看得到的：站上季線比例（合格股收盤在 60 日均線之上的比例，兩市場平均）、
加權離前高、加權 20 日漲跌、前一晚 VIX。千張大戶沒有 12 年資料，不在裡面。
在跟 bt-branch 同一層的資料夾執行：python3 live_check.py → out/live_check.json"""
import json
import os

import numpy as np
import pandas as pd

src = open("wfa_grid.py", encoding="utf-8").read()
exec(src[:src.index("CAND = {")])

W = {"第8版": (0, 0, 40, 0, 30, 15), "第7版": (0, 0, 50, 0, 35, 0), "第6版": (10, 10, 30, 15, 20, 0),
     "只看法人今日買超": (100, 0, 0, 0, 0, 0), "只看5日累計買超": (0, 100, 0, 0, 0, 0), "只看法人買超天數": (0, 0, 100, 0, 0, 0),
     "只看融資5日減少": (0, 0, 0, 100, 0, 0), "只看營收": (0, 0, 0, 0, 100, 0), "只看借券賣出少": (0, 0, 0, 0, 0, 100)}
E = {k: run(w) for k, w in W.items()}
say("名單算完", {k: [round(float(np.nanmean(E[k][1, mi])), 3) for mi in range(2)] for k in ("第8版", "第7版")})
dn = pd.DatetimeIndex(dates)

# 盤勢
elg = el.reindex(index=dates, columns=cols).fillna(False)
ma60 = adj.rolling(60, min_periods=50).mean()
ok = elg & ma60.notna()
above = (adj > ma60) & ok
br = {}
for m in MARKETS:
    cm = [c for c in cols if mkt.get(c) == m]
    br[m] = above[cm].sum(axis=1) / ok[cm].sum(axis=1).replace(0, np.nan) * 100
breadth = (br["上市"] + br["上櫃"]) / 2


def yahoo(sym):
    s = pd.Series({d: c for d, c in json.load(open(f"../bt-branch/bt/vix_hist/{sym}.json"))})
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


tw = yahoo("TWII")
dd = (tw / tw.cummax() - 1).reindex(dn, method="ffill") * 100
r20 = (tw / tw.shift(20) - 1).reindex(dn, method="ffill") * 100
vx = yahoo("VIX")
vix = pd.Series([vx[vx.index < d].iloc[-1] if (vx.index < d).any() else np.nan for d in dn], index=dn)
state = pd.DataFrame({"站上季線%": breadth.values, "離前高%": dd.values, "加權20日%": r20.values, "VIX": vix.values}, index=dn)


def two(k, hi):
    return pd.Series(np.nanmean(E[k][hi], axis=0), index=dn)  # 兩市場平均


r2 = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 2)  # noqa: E731
res = {"說明": __doc__}
res["12年平均（兩市場平均，%）"] = {k: {"5日": r2(two(k, 0).mean()), "20日": r2(two(k, 1).mean()),
                                     "5日 上市／上櫃": [r2(np.nanmean(E[k][0, 0])), r2(np.nanmean(E[k][0, 1]))],
                                     "20日 上市／上櫃": [r2(np.nanmean(E[k][1, 0])), r2(np.nanmean(E[k][1, 1]))]} for k in W}

# 雜訊：連續 N 份名單的平均超額，有多少比例跟實盤一樣差或更差
x5, x20 = two("第8版", 0).dropna(), two("第8版", 1).dropna()
noise = {}
for lab, x, n, obs in (("5日、連續18份（實盤 −0.25%）", x5, 18, -0.25), ("5日、連續8份（第8版實盤 +0.21%）", x5, 8, 0.21),
                       ("20日、連續3份（實盤 −0.45%）", x20, 3, -0.45)):
    rm = x.rolling(n).mean().dropna()
    noise[lab] = {"窗數": int(len(rm)), "平均": r2(rm.mean()), "標準差": r2(rm.std()), "跟實盤一樣差或更差的比例%": r2((rm <= obs).mean() * 100),
                  "低於0的比例%": r2((rm < 0).mean() * 100), "最差": r2(rm.min()), "10分位": r2(rm.quantile(0.1)), "90分位": r2(rm.quantile(0.9))}
res["雜訊（第8版權重，12年每一段連續N份名單）"] = noise
# 每月：一個月平均超額小於0的月份比例
mon = x5.groupby(x5.index.to_period("M")).mean()
res["每個月平均5日超額＜0的月份比例%"] = r2((mon < 0).mean() * 100)

# 盤勢分組
bins = {"站上季線%": ([0, 20, 35, 50, 65, 101], ["<20", "20~35", "35~50", "50~65", ">=65"]),
        "離前高%": ([-100, -20, -10, 0.001], ["跌超過20%", "跌10~20%", "離前高10%以內"]),
        "加權20日%": ([-100, -10, -5, 0, 5, 100], ["<-10", "-10~-5", "-5~0", "0~5", ">=5"]),
        "VIX": ([0, 20, 30, 200], ["<20", "20~30", ">=30"])}
grp = {}
for col, (b, lb) in bins.items():
    cat = pd.cut(state[col], bins=b, labels=lb, right=False)
    tab = {}
    for k in W:
        row = {}
        for hi, h in ((0, "5日"), (1, "20日")):
            s = two(k, hi)
            g = pd.DataFrame({"x": s, "c": cat}).dropna()
            row[h] = {str(c): [r2(v["x"].mean()), r2((v["x"] > 0).mean() * 100), int(len(v))] for c, v in g.groupby("c", observed=True)}
        tab[k] = row
    grp[col] = tab
res["盤勢分組（平均超額%、超額>0的比例%、天數）"] = grp
# 跟現在最像：站上季線<20 且 離前高跌超過20%
mask = (state["站上季線%"] < 20) & (state["離前高%"] < -20)
res["站上季線<20且離前高跌超過20%"] = {k: {"5日": [r2(two(k, 0)[mask].mean()), int(two(k, 0)[mask].notna().sum())],
                                          "20日": [r2(two(k, 1)[mask].mean()), int(two(k, 1)[mask].notna().sum())],
                                          "日期範圍": sorted({str(d.year) for d in dn[mask.values]})} for k in W}
state.to_csv("out/state.csv")
pd.DataFrame({k: two(k, 0) for k in W}).to_csv("out/ex5.csv")
pd.DataFrame({k: two(k, 1) for k in W}).to_csv("out/ex20.csv")
json.dump(res, open("out/live_check.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "說明"}, ensure_ascii=False, indent=1)[:12000])
