"""跑一次完整回測，結果存到 out/。用法：python run_bt.py 資料資料夾 除權息資料夾 [起日] [迄日]"""
import glob
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_eval as E  # noqa: E402
import bt_lib as B  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
pd.set_option("display.float_format", lambda v: f"{v:,.2f}")

raw, extra = sys.argv[1], sys.argv[2]
start = pd.Timestamp(sys.argv[3]) if len(sys.argv) > 3 else pd.Timestamp("2024-10-01")
end = pd.Timestamp(sys.argv[4]) if len(sys.argv) > 4 else pd.Timestamp("2100-01-01")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)
COST = 0.004  # 來回成本：證交稅 0.3% ＋ 手續費約 0.05%×2（以常見電子下單折扣估）

t0 = time.time()
paths = glob.glob(os.path.join(raw, "*.json.gz")) or glob.glob(os.path.join(raw, "*.json"))
P = B.load(paths)
ref = B.load_exright(extra)
r = B.daily_returns(P, ref)
fw = B.forward_returns(P, r)
F = B.features(P, r)
el = B.eligible(P, F)
score, parts, pen = B.site_score(P, F, el)
pick = B.top_picks(score, F, P["mkt"])
mkt = P["mkt"]
dates = P["close"].index
inrange = (dates >= start) & (dates <= end)
print(f"資料 {dates[0].date()}～{dates[-1].date()}，{len(dates)} 天、{P['close'].shape[1]} 檔；回測區間 {inrange.sum()} 天；{time.time() - t0:.0f}s")

# 只看回測區間
def rng(df):
    return df.where(pd.Series(inrange, index=dates), axis=0) if isinstance(df, pd.DataFrame) else df

pool = el & (F["instNet"] > 0)
pick_r = rng(pick).fillna(False).astype(bool)
el_r = rng(el).fillna(False).astype(bool)
pool_r = rng(pool).fillna(False).astype(bool)

results = {}
# 1) 網站名單績效
tabs = []
for h in (1, 5, 10, 20):
    for kind, key, lock in (("隔日開盤買", f"o{h}", fw["lockup"]), ("當天收盤價", f"c{h}", None)):
        daily = E.picks_daily(pick_r, fw[key], el_r, mkt, lock=lock)
        s = E.summarize(daily, h, f"{h}日・{kind}")
        tabs.append(s)
        if kind == "隔日開盤買":
            results[f"daily_o{h}"] = daily
perf = pd.concat(tabs)
print("\n=== 網站名單（前 20 名）之後的平均報酬 ===")
print(perf.to_string(index=False))
perf.to_csv(f"{OUT}/perf.csv", index=False)

# 2) 分數分十組（在當天法人買超的股票裡），各組超額
print("\n=== 分數十分組（法人買超池內）5 日超額 % ===")
dec = E.bucket_returns(rng(score), fw["o5"], pool_r, mkt, 10, bench=el_r)
print(dec.T.to_string())
dec.to_csv(f"{OUT}/deciles_o5.csv")

# 3) 單一指標 IC（合格股票全體、5 日報酬）
avg = F["avg5"]
facs = {
    "法人今日買超/均量": F["instNet"] / avg, "法人5日買超/均量": F["inst5d"] / (avg * 5),
    "連買天數(外資+1.5投信)": F["foreignDays"] + 1.5 * F["trustDays"], "融資減少/均量": -F["marginChg"].fillna(0) / avg,
    "外資今日/均量": F["foreignNet"] / avg, "投信今日/均量": F["trustNet"] / avg, "自營商今日/均量": F["dealerNet"] / avg,
    "投信20日/均量": F["trust20"] / avg, "外資20日/均量": F["foreign20"] / avg,
    "投信連買天數": F["streakT"], "外資連買天數": F["streakF"],
    "融資5日減少/均量": -F["marginAdd5"] / avg, "融資5日增幅%": F["marginUp5"], "融資餘額/均量": F["marginBal"] / avg,
    "融券增加/均量": F["shortChg"] / avg, "券資比": F["shortRatio"], "當沖比率": F["dtRatio"],
    "今日漲跌": F["ret1"], "5日漲跌": F["ret5"], "20日漲跌": F["ret20"], "60日漲跌": F["ret60"],
    "季線乖離": F["bias60"], "量能(今日/20日均)": F["volSurge"], "成交值規模": np.log(F["value20"]),
    "籌碼偏重扣分": -pen,
}
for h in (1, 5, 20):
    R = fw[f"o{h}"]
    for nm, mask in (("合格股", el_r), ("法人買超池", pool_r)):
        ft = E.factor_table({k: rng(v) for k, v in facs.items()}, R, mask, mkt, h)
        ft.to_csv(f"{OUT}/ic_o{h}_{nm}.csv", index=False)
        if h == 5:
            print(f"\n=== 指標預測力（{nm}、{h} 日）===")
            print(ft.pivot(index="指標", columns="市場", values=["IC", "IC t值", "前20%−後20% %"]).round(3).to_string())

# 4) 各季表現（5 日、隔日開盤買）
d5 = results["daily_o5"].copy()
d5["季"] = pd.PeriodIndex(d5["date"], freq="Q").astype(str)
q = d5.groupby(["季", "market"])["excess"].mean().unstack() * 100
print("\n=== 各季 5 日超額 % ===")
print(q.to_string())
q.to_csv(f"{OUT}/quarterly_o5.csv")

# 5) 存中間結果給後續分析
pd.to_pickle({"P_dates": dates, "score": score, "pen": pen, "pick": pick, "el": el, "F": F, "fw": fw, "r": r, "parts": parts,
              "mkt": mkt, "name": P["name"], "idx": P["idx"], "flows": P["flows"], "market": P["market"]}, f"{OUT}/state.pkl")
print(f"\n完成，{time.time() - t0:.0f}s")
