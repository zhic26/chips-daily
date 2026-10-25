"""主要指標在前、後兩段期間的 IC 是否穩定（5 日，合格股與法人買超池）。"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B
pd.set_option("display.width", 220); pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
st = pd.read_pickle("out/state.pkl")
F, fw, el, mkt, pen = st["F"], st["fw"], st["el"], st["mkt"], st["pen"]
avg = F["avg5"]; dates = st["P_dates"]
facs = {
    "法人今日": F["instNet"] / avg, "法人5日": F["inst5d"] / (avg * 5), "連買天數": F["foreignDays"] + 1.5 * F["trustDays"],
    "融資今日減": -F["marginChg"].fillna(0) / avg, "融資5日減": -F["marginAdd5"] / avg, "籌碼偏重(負)": -pen,
    "外資今日": F["foreignNet"] / avg, "投信今日": F["trustNet"] / avg, "外資連買": F["streakF"], "投信連買": F["streakT"],
    "外資5日天數": F["foreignDays"], "投信5日天數": F["trustDays"],
    "當沖比率": F["dtRatio"], "5日漲跌": F["ret5"], "今日漲跌": F["ret1"], "20日漲跌": F["ret20"], "量能暴增": F["volSurge"],
    "融資5日增幅": F["marginUp5"], "規模": np.log(F["value20"].where(F["value20"] > 0)),
}
segs = {"前段24/10-25/09": (pd.Timestamp("2024-10-01"), pd.Timestamp("2025-09-30")),
        "後段25/10-26/10": (pd.Timestamp("2025-10-01"), pd.Timestamp("2026-12-31"))}
pool = el & (F["instNet"] > 0)
rows = []
for seg, (a, b) in segs.items():
    m = pd.Series((dates >= a) & (dates <= b), index=dates)
    for nm, mask in (("合格股", el), ("法人買超池", pool)):
        mk = mask.where(m, axis=0).fillna(False).astype(bool)
        for k, X in facs.items():
            for mm in ("上市", "上櫃"):
                c = mkt.index[mkt == mm]
                ic = E.rowwise_ic(X[c], fw["o5"][c], mk[c])
                rows.append({"段": seg, "範圍": nm, "指標": k, "市場": mm, "IC": ic.mean(), "t": E.tstat(ic.values, 5)})
T = pd.DataFrame(rows)
for nm in ("合格股", "法人買超池"):
    print(f"\n=== {nm}：5 日 IC（t 值）===")
    t = T[T["範圍"] == nm].copy()
    t["v"] = t.apply(lambda r: f"{r['IC']:+.3f} ({r['t']:+.1f})", axis=1)
    print(t.pivot_table(index="指標", columns=["段", "市場"], values="v", aggfunc="first").to_string())
