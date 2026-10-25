"""盤勢（大盤體溫）跟名單表現的關係。用法：python regime.py out/state.pkl"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_eval as E  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
st = pd.read_pickle(sys.argv[1])
start = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp("2024-10-01")
F, fw, el, pick, mkt = st["F"], st["fw"], st["el"], st["pick"], st["mkt"]
dates = st["P_dates"]

reg = pd.DataFrame(index=dates)
for m in ("上市", "上櫃"):
    c = mkt.index[mkt == m]
    b = F["bias60"][c]
    reg[f"站上季線%_{m}"] = (b > 0).sum(axis=1) / b.notna().sum(axis=1) * 100
ix = pd.Series({d: (st["idx"].get(d) or {}).get("加權指數", {}).get("close") for d in dates}, dtype=float)
reg["加權20日漲跌%"] = (ix / ix.shift(20) - 1) * 100
reg["加權在季線上"] = (ix > ix.rolling(60, min_periods=50).mean()).astype(float)
fx = pd.Series({d: (st["flows"].get(d) or {}).get("外資") for d in dates}, dtype=float)
reg["外資5日買賣超億"] = fx.rolling(5, min_periods=5).sum() / 1e8
mg = pd.Series({d: (st["market"].get(d) or {}).get("marginAmt") for d in dates}, dtype=float)
reg["融資5日增減億"] = (mg - mg.shift(5)) / 1e5
val = pd.Series({d: (st["market"].get(d) or {}).get("value") for d in dates}, dtype=float)
reg["量能比20日均"] = val / val.rolling(20, min_periods=15).mean()

inr = pd.Series(dates >= start, index=dates)
pk = pick.where(inr, axis=0).fillna(False).astype(bool)
elr = el.where(inr, axis=0).fillna(False).astype(bool)
for h in (5, 20):
    daily = E.picks_daily(pk, fw[f"o{h}"], elr, mkt, lock=fw["lockup"])
    print(f"\n===== 名單 {h} 日超額（%）依盤勢分組 =====")
    for m in ("上市", "上櫃"):
        g = daily[daily["market"] == m].set_index("date").join(reg)
        print(f"--- {m}（{len(g)} 天，平均 {g['excess'].mean() * 100:.2f}%）")
        for col in [f"站上季線%_{m}", "加權20日漲跌%", "外資5日買賣超億", "融資5日增減億", "量能比20日均", "加權在季線上"]:
            x = g[[col, "excess", "univ"]].dropna()
            if x[col].nunique() <= 2:
                grp = x.groupby(x[col])
            else:
                grp = x.groupby(pd.qcut(x[col], 3, labels=["低", "中", "高"]), observed=True)
            s = grp.agg(天數=("excess", "size"), 超額=("excess", "mean"), 大盤=("univ", "mean"),
                        區間=(col, lambda v: f"{v.min():.0f}～{v.max():.0f}"))
            s[["超額", "大盤"]] *= 100
            print(f"  {col}:", "  ".join(f"[{i}] {r['區間']}：超額 {r['超額']:.2f}%（大盤 {r['大盤']:.2f}%，{r['天數']} 天）" for i, r in s.iterrows()))
reg.to_csv(os.path.join(os.path.dirname(sys.argv[1]), "regime.csv"))
