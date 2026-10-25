"""名單選出後第 1～20 天的累積超額（事件研究），以及「每天買進名單、持有 H 天」的資產曲線。
用法：python portfolio.py out/state.pkl [H]"""
import os
import sys

import numpy as np
import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
st = pd.read_pickle(sys.argv[1])
H = int(sys.argv[2]) if len(sys.argv) > 2 else 5
start = pd.Timestamp("2024-10-01")
F, el, pick, mkt, r = st["F"], st["el"], st["pick"], st["mkt"], st["r"]
P_open_close = st["fw"]  # 只用到 lockup
dates = st["P_dates"]
close = F["close"]

# 隔天開盤買進：第 1 天報酬＝收盤/開盤，之後用還原後的每日報酬
L = np.log1p(r.fillna(0)).cumsum()
openp = None
state_dir = os.path.dirname(sys.argv[1])

# 事件研究
rows = []
inr = pd.Series(dates >= start, index=dates)
for m in ("上市", "上櫃"):
    c = mkt.index[mkt == m]
    pk = pick[c].where(inr, axis=0).fillna(False).astype(bool) & ~st["fw"]["lockup"][c].fillna(False).astype(bool)
    elm = el[c].where(inr, axis=0).fillna(False).astype(bool)
    g1 = st["fw"]["o1"][c]
    for h in range(1, 21):
        R = (1 + g1) * np.exp(L[c].shift(-h) - L[c].shift(-1)) - 1
        p = R.where(pk).mean(axis=1)
        u = R.where(elm & R.notna()).mean(axis=1)
        ex = (p - u).dropna()
        rows.append({"市場": m, "第幾天": h, "累積超額%": ex.mean() * 100, "名單報酬%": p.dropna().mean() * 100,
                     "大盤等權%": u[ex.index].mean() * 100})
ev = pd.DataFrame(rows)
print("=== 選出後第 N 天收盤的累積報酬（隔日開盤買）===")
print(ev.pivot(index="第幾天", columns="市場", values=["累積超額%", "名單報酬%", "大盤等權%"]).to_string())
ev.to_csv(os.path.join(state_dir, "event.csv"), index=False)

# 資產曲線：每天把資金的 1/H 買進當天名單（隔日開盤買、持有 H 天）。
# 對照組用一模一樣的買法買「同市場所有合格股」，兩邊都扣同樣的來回成本，差距才是選股本身的效果。
COST = 0.004
for m in ("上市", "上櫃"):
    c = mkt.index[mkt == m]
    pk = pick[c].fillna(False).astype(bool) & ~st["fw"]["lockup"][c].fillna(False).astype(bool)
    un = el[c].fillna(False).astype(bool)
    rr = r[c]
    g1 = st["fw"]["o1"][c].shift(1)  # 第 T+1 天開盤到收盤（放在 T+1 那一列）
    idx = list(dates)
    port = {"名單": pd.Series(0.0, index=dates), "全部合格股（同樣買法）": pd.Series(0.0, index=dates)}
    for i, d in enumerate(idx[:-H - 1]):
        if d < start:
            continue
        for lab, sel in (("名單", pk), ("全部合格股（同樣買法）", un)):
            names = list(sel.columns[sel.loc[d]])
            if not names:
                continue
            for k in range(1, H + 1):
                dk = idx[i + k]
                day_r = g1.loc[dk, names] if k == 1 else rr.loc[dk, names]
                port[lab][dk] += day_r.fillna(0).mean() / H
            port[lab][idx[i + 1]] -= COST / H
    cv = pd.DataFrame(port).loc[start:]
    hold = rr.where(un.shift(1).fillna(False).astype(bool)).mean(axis=1).loc[start:]  # 一直抱著等權大盤（收盤到收盤、不換股）
    eq = (1 + cv).cumprod()
    eq["一直抱著（等權大盤）"] = (1 + hold.fillna(0)).cumprod()
    yrs = len(cv) / 245
    print(f"\n=== {m}：每天買進、持有 {H} 天、扣來回成本 {COST * 100:.1f}% ===")
    for col in eq.columns:
        e = eq[col]
        print(f"  {col}：總報酬 {(e.iloc[-1] - 1) * 100:+.1f}%（年化 {(e.iloc[-1] ** (1 / yrs) - 1) * 100:+.1f}%），最大回落 {((e / e.cummax()) - 1).min() * 100:.1f}%")
    rel = eq["名單"] / eq["全部合格股（同樣買法）"]
    print(f"  名單相對同樣買法的大盤：{(rel.iloc[-1] - 1) * 100:+.1f}%")
    eq.to_csv(os.path.join(state_dir, f"equity_{m}_H{H}.csv"))
