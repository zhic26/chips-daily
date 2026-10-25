"""從回測狀態挑出每天的集保候選股（法人買超池內、扣大戶項前分數前 K 名），列出要查的（代號, 週別）。
用法：python tdcc_jobs.py state.pkl probe.json 輸出資料夾 K 份數"""
import json
import os
import sys

import pandas as pd

st = pd.read_pickle(sys.argv[1])
weeks = sorted(json.load(open(sys.argv[2]))["weeks"])  # 舊到新
outdir, K, parts = sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
os.makedirs(outdir, exist_ok=True)

score, F, el, mkt = st["score"], st["F"], st["el"], st["mkt"]
pool = el & (F["instNet"] > 0)
wk = [pd.Timestamp(w) for w in weeks]


def week_for(d):
    """選股日 d 可用的最新一週（資料日嚴格早於 d），以及再前一週。"""
    prior = [w for w in wk if w < d]
    if len(prior) < 2:
        return None, None
    return prior[-1], prior[-2]


need = set()
cand_rows = []
for d in score.index:
    w, wp = week_for(d)
    if w is None:
        continue
    for m in ("上市", "上櫃"):
        cols = mkt.index[mkt == m]
        s = score.loc[d, cols].where(pool.loc[d, cols]).dropna().sort_values(ascending=False)
        top = list(s.index[:K])
        for c in top:
            need.add((c, w.strftime("%Y%m%d")))
            need.add((c, wp.strftime("%Y%m%d")))
            cand_rows.append((d.strftime("%Y-%m-%d"), c, w.strftime("%Y%m%d"), wp.strftime("%Y%m%d")))
need = sorted(need, key=lambda x: (x[1], x[0]))
print("候選股票-日：", len(cand_rows), "需要查詢：", len(need), "檔次；不同股票", len({c for c, _ in need}))
pd.DataFrame(cand_rows, columns=["date", "code", "week", "prev"]).to_csv(os.path.join(outdir, "candidates.csv"), index=False)
for k in range(parts):
    with open(os.path.join(outdir, f"part{k + 1}.txt"), "w") as fh:
        for c, w in need[k::parts]:
            fh.write(f"{c} {w}\n")
