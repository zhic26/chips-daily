import sys, os, numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B
st = pd.read_pickle("out/state.pkl"); X2 = sys.argv[1]
F, fw, el, mkt = st["F"], st["fw"], st["el"], st["mkt"]; dates = st["P_dates"]; avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)
rv = pd.read_csv(os.path.join(X2, "revenue.csv"), dtype={"code": str}).drop_duplicates(["ym", "code"])
rev = rv.pivot(index="ym", columns="code", values="rev").sort_index(); ly = rv.pivot(index="ym", columns="code", values="rev_ly").sort_index()
yoy3 = (rev.rolling(3).sum() / ly.rolling(3).sum() - 1).where(ly.rolling(3).sum() > 0) * 100
yoy3.index = pd.to_datetime(yoy3.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)
Y3 = yoy3.reindex(yoy3.index.union(dates)).ffill().reindex(dates).reindex(columns=F["close"].columns)
I1, I5, C, M5, R = pct(F["instNet"] / avg), pct(F["inst5d"] / (avg * 5)), pct(F["foreignDays"] + 1.5 * F["trustDays"]), pct(-F["marginAdd5"].fillna(0) / avg), pct(Y3)
R = R.fillna(0.5)  # 沒有營收資料（新上市等）給中間值
sets = {"現行 10/15/30/20/大戶25/營收0": (10, 15, 30, 20, 0), "R1 10/10/25/15/大戶20/營收20": (10, 10, 25, 15, 20),
        "R2 10/15/25/15/大戶20/營收15": (10, 15, 25, 15, 15), "R3 5/10/25/15/大戶20/營收25": (5, 10, 25, 15, 25),
        "R4 10/10/30/15/大戶15/營收20": (10, 10, 30, 15, 20)}
segs = (("前", "2024-10-01", "2025-09-30"), ("後", "2025-10-01", "2026-12-31"))
rows = []
for name, (a, b, c, m, r) in sets.items():
    sc = a * I1 + b * I5 + c * C + m * M5 + r * R
    pk = B.top_picks(sc.where(el), F, mkt)
    row = {"權重 今日/5日/連買/融資/大戶/營收": name}
    for h in (5, 20):
        d = E.picks_daily(pk, fw[f"o{h}"], el, mkt, lock=fw["lockup"])
        for seg, s0, s1 in segs:
            g = d[(d["date"] >= s0) & (d["date"] <= s1)]
            row[f"{h}日{seg}段"] = round(g.groupby("date")["excess"].mean().mean() * 100, 2)
        if h == 20:
            pr = pk & ~fw["lockup"].fillna(False).astype(bool)
            v = fw["o20"].where(pr).stack().dropna(); v = v[v.index.get_level_values(0) >= pd.Timestamp("2024-10-01")]
            row["20日跌逾15%比例"] = round((v < -0.15).mean() * 100, 1)
    prev = pk.shift(1).fillna(False).astype(bool)
    row["換手%"] = round(((pk & ~prev).sum(axis=1) / pk.sum(axis=1).replace(0, np.nan)).loc["2024-10-01":].mean() * 100)
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))
