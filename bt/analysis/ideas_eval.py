"""其他網站常見、或我們還沒試過的想法：先用現有資料粗篩。只印精簡表。
用法：python ideas_eval.py"""
import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, ".")
import bt_eval as E, bt_lib as B  # noqa: E402

st = pd.read_pickle("out/state.pkl")
F, fw, el, mkt = st["F"], st["fw"], st["el"], st["mkt"]; dates = st["P_dates"]; avg = F["avg5"]
pct = lambda X: B.pct_in_market(X, el, mkt)  # noqa: E731
rv = pd.read_csv("../bt-branch/bt/extra2/revenue.csv", dtype={"code": str}).drop_duplicates(["ym", "code"])
rev = rv.pivot(index="ym", columns="code", values="rev").sort_index(); ly = rv.pivot(index="ym", columns="code", values="rev_ly").sort_index()
y3 = (rev.rolling(3).sum() / ly.rolling(3).sum() - 1).where(ly.rolling(3).sum() > 0) * 100
y3.index = pd.to_datetime(y3.index + "-01") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10)
Y3 = y3.reindex(y3.index.union(dates)).ffill().reindex(dates).reindex(columns=F["close"].columns)
comp = json.load(open("/home/claude/chips-daily/data/meta/companies.json"))["data"]
ind = pd.Series({c: (comp.get(c) or {}).get("industry") or ("NA" + c) for c in F["close"].columns})

P = {"it": pct(F["instNet"] / avg), "i5": pct(F["inst5d"] / (avg * 5)), "co": pct(F["foreignDays"] + 1.5 * F["trustDays"]),
     "mg": pct(-F["marginAdd5"].fillna(0) / avg), "rv": pct(Y3).fillna(0.5)}
W0 = 10 * P["it"] + 10 * P["i5"] + 30 * P["co"] + 15 * P["mg"] + 20 * P["rv"]


def pct_group(X, min_n=8):
    """產業內百分位（同市場、同產業合格股至少 min_n 檔才用，否則用全市場）。"""
    out = pct(X)
    for _, cols in pd.DataFrame({"m": mkt.reindex(X.columns), "g": ind}).groupby(["m", "g"]).groups.items():
        cols = list(cols)
        xm = X[cols].where(el[cols])
        n = xm.notna().sum(axis=1)
        p = xm.rank(axis=1).sub(1).div((n - 1).replace(0, np.nan), axis=0)
        ok = np.repeat(n.ge(min_n).values[:, None], len(cols), axis=1)
        out[cols] = p.where(ok, out[cols])
    return out


def capped(score, cap=3, n=20):
    s = score.where(el & (F["instNet"] > 0)) + F["instNet"].clip(lower=0) * 1e-9
    pick = np.zeros(s.shape, dtype=bool)
    col = {c: i for i, c in enumerate(s.columns)}
    for m in ("上市", "上櫃"):
        cols = list(mkt.index[mkt == m])
        sub = s[cols].values
        for di in range(len(s)):
            row = sub[di]
            order = np.argsort(-np.nan_to_num(row, nan=-1e9))
            cnt, k = {}, 0
            for j in order:
                if np.isnan(row[j]) or k >= n:
                    break
                g = ind[cols[j]]
                if cnt.get(g, 0) >= cap:
                    continue
                cnt[g] = cnt.get(g, 0) + 1
                pick[di, col[cols[j]]] = True
                k += 1
    return pd.DataFrame(pick, index=s.index, columns=s.columns)


ft = F["foreignNet"] + F["trustNet"]
ft5 = ft.rolling(5, min_periods=5).sum()
mom = (1 + F["ret60"]) / (1 + F["ret5"]) - 1
prox = F["close"] / F["close"].rolling(120, min_periods=100).max()
V = {
    "現行": (W0, None, None),
    "法人只算外資＋投信（不含自營商）": (W0 - 10 * P["it"] - 10 * P["i5"] + 10 * pct(ft / avg) + 10 * pct(ft5 / (avg * 5)), ft > 0, None),
    "營收改成產業內比較": (W0 - 20 * P["rv"] + 20 * pct_group(Y3).fillna(0.5), None, None),
    "＋中期動能 10 分（60 日漲幅，不含最近 5 日）": (W0 + 10 * pct(mom).fillna(0.5), None, None),
    "＋接近半年高點 10 分": (W0 + 10 * pct(prox).fillna(0.5), None, None),
    "＋短期反轉 10 分（最近 5 日跌越多越高）": (W0 + 10 * pct(-F["ret5"]).fillna(0.5), None, None),
    "同產業最多 3 檔": (W0, None, 3),
}
inr = pd.Series(dates >= pd.Timestamp("2024-10-01"), index=dates)
elr = el.where(inr, axis=0).fillna(False).astype(bool)
rows = []
for name, (sc, pool, cap) in V.items():
    pk = capped(sc, cap) if cap else B.top_picks(sc.where(el), F, mkt, pool_mask=None if pool is None else pool & el)
    pk = pk.where(inr, axis=0).fillna(False).astype(bool)
    row = {"方式": name}
    for h in (5, 20):
        d = E.picks_daily(pk, fw[f"o{h}"], elr, mkt, lock=fw["lockup"])
        s = E.summarize(d, h).set_index("市場")
        for m in ("上市", "上櫃"):
            row[f"{h}日{m}"] = round(s.loc[m, "超額%"], 2)
        row[f"{h}日t"] = round(s.loc["合計", "t值"], 1)
        late = d[d["date"] >= "2025-10-01"].groupby("date")["excess"].mean()
        row[f"{h}日後段"] = round(late.mean() * 100, 2)
    if name == "現行" or cap:
        top = pk.loc[pk.index >= "2024-10-01"]
        conc = [max(pd.Series(ind[top.columns[r]]).value_counts().max(), 0) for r in top.values if r.any()]
        row["最多同產業"] = round(np.mean(conc), 1)
    rows.append(row)
print("前 20 名平均超額（%，對同市場合格股等權，隔日開盤買）。t：上市櫃合計、不重疊抽樣。後段：2025/10 以後")
print(pd.DataFrame(rows).fillna("").to_string(index=False))
