"""外資台指期淨空單在歷史上算不算多（2026-11-20，使用者的問題）。
資料：期交所網站只提供近三年（bt/fut_hist，2023/12 起），更早用 FinMind 公開 API（bt/fut_finmind，2018/6 起，跟官網重疊的 719 天三大法人全部一致）；2018/6 以前要向期交所書面申請。加權指數收盤用 bt/raw＋網站 data/daily，
2026/11/18～20 用網站與新聞的收盤補上。
- 臺股期貨（大台）外資、投信、自營商的未平倉多空淨額（口、契約金額）；三大法人以外的人＝三者相加的負數（全市場多空相抵）。
- 小型臺指換成大台口數 ÷4，合計看「大台約當」（微型臺指 2024/7 才有、FinMind 沒有，不算）。
- 各年份中位數、目前在歷史上的百分位、歷史最多的淨空單。
- 過去幾次跌超過 20% 的高點、谷底前後，外資淨空單怎麼變；空單最多的那天跟指數谷底差幾天。
- 外資 5 天內回補（淨空單少）超過 1 萬口之後，加權 20 天的表現，跟所有日子比。
在跟 bt-branch 同一層的資料夾執行：python3 fut_check.py → out/fut_check.json"""
import glob
import gzip
import io
import json
import os

import numpy as np
import pandas as pd

BT = "../bt-branch/bt"
SITE = "/home/claude/chips-daily"
num = lambda s: pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")  # noqa: E731


def load_fm(did):
    """FinMind（2018/6 起）：多空未平倉淨額＝多方－空方（口）；契約金額（千元 → 億）。"""
    rs = []
    for p in sorted(glob.glob(f"{BT}/fut_finmind/{did}_*.json")):
        rs += json.load(open(p))["data"]
    d = pd.DataFrame(rs)
    d["date"] = pd.to_datetime(d["date"])
    d["who"] = d["institutional_investors"].map(lambda s: "外資" if "外資" in s else s)
    d["net"] = d["long_open_interest_balance_volume"] - d["short_open_interest_balance_volume"]
    d["net_amt"] = (d["long_open_interest_balance_amount"] - d["short_open_interest_balance_amount"]) / 1e5
    return d.pivot_table(index="date", columns="who", values="net", aggfunc="first").sort_index(), \
        d.pivot_table(index="date", columns="who", values="net_amt", aggfunc="first").sort_index()


def load_off():
    """期交所官網 CSV（2023/12 起），用來對帳。"""
    rows = [pd.read_csv(p, dtype=str) for p in sorted(glob.glob(f"{BT}/fut_hist/*.csv"))]
    o = pd.concat(rows, ignore_index=True)
    o.columns = [c.strip() for c in o.columns]
    o = o[o["商品名稱"].str.strip() == "臺股期貨"]
    o["date"] = pd.to_datetime(o["日期"].str.strip(), format="%Y/%m/%d")
    o["who"] = o["身份別"].str.strip().map(lambda s: "外資" if s.startswith("外資") else s)
    o["net"] = num(o["多空未平倉口數淨額"])
    return o.pivot_table(index="date", columns="who", values="net", aggfunc="first").sort_index()


tx, tx_amt = load_fm("TX")
mtx, _ = load_fm("MTX")
off = load_off()
common = off.index.intersection(tx.index)
check = {w: f"{int((off.loc[common, w] == tx.loc[common, w]).sum())}/{len(common)}" for w in ("外資", "投信", "自營商")}
print("FinMind 跟期交所官網重疊的日子一致：", check, flush=True)
tx["其他"] = -(tx[["外資", "投信", "自營商"]].sum(axis=1))
eq = tx[["外資", "投信", "自營商"]].add(mtx[["外資", "投信", "自營商"]].reindex(tx.index).fillna(0) / 4)  # 大台約當（加小台）

# 加權指數收盤
cl = {}
for f in sorted(glob.glob(f"{BT}/raw/*.json.gz")):
    d = json.load(gzip.open(f))
    c = (d.get("indices") or {}).get("加權指數", {}).get("close")
    if c:
        cl[os.path.basename(f)[:10]] = c
for f in sorted(os.listdir(f"{SITE}/data/daily")):
    d = json.load(open(f"{SITE}/data/daily/{f}", encoding="utf-8"))
    c = (d.get("indices") or {}).get("加權指數", {}).get("close")
    if c:
        cl[f[:10]] = c
cl.update({"2026-11-18": 40194.91, "2026-11-19": 38426.89, "2026-11-20": 36033.29})
idx = pd.Series(cl)
idx.index = pd.to_datetime(idx.index)
idx = idx.sort_index()
D = tx.index.intersection(idx.index)
F = tx["外資"].reindex(D)
T_ = tx["投信"].reindex(D)
I = idx.reindex(D)
last = D[-1]
r2 = lambda x: None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 2)  # noqa: E731
res = {"說明": __doc__, "期間": f"{D[0].date()}～{last.date()}", "天數": len(D), "跟期交所官網對帳": check}

# 1. 每年
yr = {}
for y, g in tx.groupby(tx.index.year):
    yr[int(y)] = {"外資淨額中位數": int(g["外資"].median()), "外資最多淨空": int(g["外資"].min()), "外資最多淨多": int(g["外資"].max()),
                  "投信淨額中位數": int(g["投信"].median()), "自營淨額中位數": int(g["自營商"].median()), "其他（散戶等）中位數": int(g["其他"].median()),
                  "外資淨額契約金額中位數（億）": r2(tx_amt.loc[g.index, "外資"].median())}
res["每年（大台）"] = yr

# 2. 目前的位置
cur = {"日期": str(last.date()), "外資": int(F.iloc[-1]), "投信": int(T_.iloc[-1]), "自營商": int(tx["自營商"].loc[last]), "其他": int(tx["其他"].loc[last]),
       "外資契約金額（億）": r2(tx_amt["外資"].loc[last]) if last in tx_amt.index else None}
cur["外資淨空在2018/6以來的百分位（越高越多空）"] = r2((F > F.iloc[-1]).mean() * 100)
cur["外資＋投信（扣掉跟投信對作）"] = int(F.iloc[-1] + T_.iloc[-1])
FT = F + T_
cur["外資＋投信在2018/6以來的百分位（越高越多空）"] = r2((FT > FT.iloc[-1]).mean() * 100)
amt = tx_amt["外資"].reindex(D)
cur["外資契約金額在2018/6以來的百分位"] = r2((amt > amt.iloc[-1]).mean() * 100)
for nm, s_ in (("外資", F), ("外資＋投信", FT), ("外資大台約當（含小台）", eq["外資"].reindex(D))):
    k = s_.idxmin()
    cur[f"歷史最多淨空：{nm}"] = [str(k.date()), int(s_.min())]
res["目前"] = cur
# 近兩年每月底
res["每月底（2024 起）"] = {str(d.date()): [int(F.loc[d]), int(T_.loc[d]), int(FT.loc[d])] for d in F[F.index >= "2024-01-01"].groupby(F[F.index >= "2024-01-01"].index.to_period("M")).apply(lambda s: s.index[-1])}

# 3. 跌超過 20% 的幾次
dd = I / I.cummax() - 1
eps = [("2020-01-14", "2020-03-19"), ("2022-01-04", "2022-10-25"), ("2024-07-11", "2025-04-09"), ("2026-10-06", str(last.date()))]
small = [("2024-07-11", "2024-08-05")]  # 2015 年那次在 2018/6 以前，沒有資料
ep = {}
pos = {d: i for i, d in enumerate(D)}
for pk, tr in eps + small:
    pk, tr = pd.Timestamp(pk), pd.Timestamp(tr)
    if pk not in pos or tr not in pos:
        continue
    win = F.loc[pk:tr]
    kmin = win.idxmin()
    after = F.iloc[pos[tr]:pos[tr] + 21]
    o = {"指數跌幅%": r2((I.loc[tr] / I.loc[pk] - 1) * 100), "高點那天外資": int(F.loc[pk]), "谷底那天外資": int(F.loc[tr]),
         "期間最多淨空": [str(kmin.date()), int(win.min())], "最多淨空那天到谷底（交易日）": pos[tr] - pos[kmin],
         "谷底那天投信": int(T_.loc[tr]), "谷底後20天外資": int(after.iloc[-1]) if len(after) > 20 else None,
         "谷底後20天加權%": r2((I.iloc[pos[tr] + 20] / I.loc[tr] - 1) * 100) if pos[tr] + 20 < len(D) else None}
    ep[f"{pk.date()}～{tr.date()}"] = o
res["大跌期間"] = ep

# 4. 回補之後
d5 = F - F.shift(5)
fw = I.shift(-20) / I - 1
base = fw.dropna()
sig = {}
for th in (5000, 10000, 15000):
    for nm, m_ in ((f"5天回補≥{th}", d5 >= th), (f"5天加空≥{th}", d5 <= -th)):
        x = fw[m_].dropna()
        # 同一段只算第一天（避免連續好幾天重複算）
        firsts = m_ & ~m_.shift(1, fill_value=False)
        x1 = fw[firsts].dropna()
        sig[nm] = {"天數": int(len(x)), "20天後平均%": r2(x.mean() * 100), "上漲比例%": r2((x > 0).mean() * 100),
                   "只算每段第一天：段數": int(len(x1)), "平均%": r2(x1.mean() * 100), "上漲%": r2((x1 > 0).mean() * 100)}
sig["所有日子"] = {"天數": int(len(base)), "20天後平均%": r2(base.mean() * 100), "上漲比例%": r2((base > 0).mean() * 100)}
# 大跌中（離高點 −15% 以下）才回補
m15 = (d5 >= 10000) & (dd <= -0.15)
x = fw[m15].dropna()
sig["離高點−15%以下且5天回補≥10000"] = {"天數": int(len(x)), "20天後平均%": r2(x.mean() * 100), "上漲比例%": r2((x > 0).mean() * 100),
                                   "日期（每段第一天）": [str(d.date()) for d in m15[m15 & ~m15.shift(1, fill_value=False)].index]}
x = fw[dd <= -0.15].dropna()
sig["離高點−15%以下的所有日子"] = {"天數": int(len(x)), "20天後平均%": r2(x.mean() * 100), "上漲比例%": r2((x > 0).mean() * 100)}
res["回補之後"] = sig
res["相關"] = {"5天外資淨額變化 vs 之後20天加權": r2(d5.corr(fw)), "外資淨額水準 vs 之後20天加權": r2(F.corr(fw))}
os.makedirs("out", exist_ok=True)
json.dump(res, open("out/fut_check.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "說明"}, ensure_ascii=False, indent=1))
