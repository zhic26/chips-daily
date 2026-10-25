"""比較不同計分方式：每種方式每天選上市、上櫃各 20 檔，看前後兩段期間的 5/10/20 日超額。
用法：python variants.py out/state.pkl 切分日（前段＝調參、後段＝驗證）"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bt_eval as E  # noqa: E402
import bt_lib as B  # noqa: E402

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.float_format", lambda v: f"{v:,.2f}")

st = pd.read_pickle(sys.argv[1])
split = pd.Timestamp(sys.argv[2]) if len(sys.argv) > 2 else pd.Timestamp("2025-10-01")
start = pd.Timestamp("2024-10-01")
F, fw, el, mkt, pen = st["F"], st["fw"], st["el"], st["mkt"], st["pen"]
dates = st["P_dates"]
avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)  # noqa: E731

P = {
    "I1": pct(F["instNet"] / avg), "I5": pct(F["inst5d"] / (avg * 5)),
    "C": pct(F["foreignDays"] + 1.5 * F["trustDays"]), "M": pct(-F["marginChg"].fillna(0) / avg),
    "FT1": pct((F["foreignNet"] + F["trustNet"]) / avg),
    "FT5": pct((F["foreignNet"] + F["trustNet"]).rolling(5, min_periods=5).sum() / (avg * 5)),
    "T1": pct(F["trustNet"] / avg), "T5": pct(F["trustNet"].rolling(5, min_periods=5).sum() / (avg * 5)),
    "F1": pct(F["foreignNet"] / avg), "F5": pct(F["foreignNet"].rolling(5, min_periods=5).sum() / (avg * 5)),
    "T20": pct(F["trust20"] / avg), "DT": pct(F["dtRatio"]), "R5": pct(F["ret5"]), "R20": pct(F["ret20"]),
    "M5": pct(-F["marginAdd5"] / avg),
    "TD": pct(F["trustDays"]), "FD": pct(F["foreignDays"]), "C2": pct(F["foreignDays"] + 3 * F["trustDays"]),
    "VS": pct(F["volSurge"]), "SZ": pct(np.log(F["value20"].where(F["value20"] > 0))),
}


def run(score, pool=None):
    pool = (F["instNet"] > 0) if pool is None else pool
    pk = B.top_picks(score.where(el), F, mkt, pool_mask=pool)
    res = {}
    for h in (5, 10, 20):
        d = E.picks_daily(pk, fw[f"o{h}"], el, mkt, lock=fw["lockup"])
        d = d[d["date"] >= start]
        for seg, g in (("前段", d[d["date"] < split]), ("後段", d[d["date"] >= split])):
            gg = g.groupby("date")[["excess"]].mean()
            res[(f"{h}日", seg)] = (gg["excess"].mean() * 100, E.tstat(gg["excess"].values, h))
    # 換手率：今天名單有多少是昨天沒有的
    prev = pk.shift(1).fillna(False).astype(bool)
    new = (pk & ~prev).sum(axis=1) / pk.sum(axis=1).replace(0, np.nan)
    res[("換手", "全期")] = (new[new.index >= start].mean() * 100, np.nan)
    return res


base = 25 * P["I1"] + 25 * P["I5"] + 10 * P["C"] + 15 * P["M"] + 12.5
V = {
    "A 現行規則": base - pen,
    "B 現行＋三個扣分(當沖/5日漲幅/爆量)": base - pen - 8 * P["DT"] - 8 * P["R5"] - 6 * P["VS"],
    "C 改權重(重連買、輕金額、融資看5日)": 10 * P["I1"] + 15 * P["I5"] + 25 * P["C"] + 15 * P["M5"] + 12.5 - pen,
    "D 改權重＋三個扣分": 10 * P["I1"] + 15 * P["I5"] + 25 * P["C"] + 15 * P["M5"] + 12.5 - pen - 8 * P["DT"] - 8 * P["R5"] - 6 * P["VS"],
    "E 連買改成投信加倍": 10 * P["I1"] + 15 * P["I5"] + 25 * P["C2"] + 15 * P["M5"] + 12.5 - pen - 8 * P["DT"] - 8 * P["R5"] - 6 * P["VS"],
    "F 只用連買＋扣分": 50 * P["C2"] + 12.5 - pen - 8 * P["DT"] - 8 * P["R5"] - 6 * P["VS"],
    "G 現行不扣籌碼偏重": base,
}
extra = {k: v for k, v in (a.split("=", 1) for a in sys.argv[3:])}  # 允許命令列加變體：名稱=運算式
for k, expr in extra.items():
    V[k] = eval(expr, {"P": P, "pen": pen, "base": base, "F": F, "np": np, "pct": pct, "avg": avg})

rows = []
for name, sc in V.items():
    r = run(sc)
    row = {"計分方式": name}
    for (h, seg), (m, t) in r.items():
        row[f"{h}{seg}"] = m
        if seg != "全期":
            row[f"{h}{seg}t"] = t
    rows.append(row)
out = pd.DataFrame(rows)
cols = ["計分方式"] + [c for c in out.columns if c != "計分方式" and not c.endswith("t")] + [c for c in out.columns if c.endswith("t")]
print(f"切分日 {split.date()}（前段 {start.date()}～，後段～最後）；數字＝上市上櫃合計的平均超額 %，t＝非重疊 t 值")
print(out[cols].to_string(index=False))
out.to_csv(os.path.join(os.path.dirname(sys.argv[1]), "variants.csv"), index=False)
