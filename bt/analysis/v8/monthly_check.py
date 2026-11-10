"""小資版（每月買名單分數最高的 N 檔、抱滿 60 天）第 7 版 vs 第 8 版：結果很看「剛好挑到哪一檔」，
所以把進場日從每月第 1 個交易日換成第 1～10 個交易日各跑一次，看分布（2026-11-10）。結果存 out/monthly_check.json"""
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
DOC = __doc__
t0 = time.time()
src = open("solutions.py", encoding="utf-8").read()
exec(src[src.index('sys.path.insert(0, ".")'):src.index("def run(")].replace('sys.path.insert(0, ".")\nt0 = time.time()\n', ""))

W7 = 50 * pct(days) + 35 * pct(Y3).fillna(0.5)
INST = P["tot"].fillna(0) / LOT  # solutions.py 的段落把 tot 拿去算站上季線的家數了，這裡重算法人買超（張）
VER = {}
for name, W in (("第7版", W7), ("第8版", W0)):
    pkd = B.top_picks(W.where(el), {"instNet": INST}, mkt)
    VER[name] = (pkd.reindex(index=dates, columns=cols).fillna(False).values.astype(bool), W.values)
print("第8版名單跟 long_setup 的 pk 一樣：", bool((VER["第8版"][0] == pkv).all()), flush=True)
months_of = {}
for t in range(start + 1, T):
    months_of.setdefault((dates[t].year, dates[t].month), []).append(t)


def run2(pkv_, SC_, entry, N=1, H=60, cost=0.004, filt=None):
    BUY = (cost - 0.003) / 2
    SELL = BUY + 0.003
    cash, units, idx_u, pos = 0.0, 0.0, 0.0, []
    nav = np.full(T - start - 1, np.nan)
    flows = []
    for t in range(start + 1, T):
        if t in entry:
            v_pre = cash + idx_u * tx[t - 1] + sum(p[1] * last_close(t - 1, p[0], p[2]) for p in pos)
            units += 1.0 / (v_pre / units) if units > 0 else 1.0
            flows.append(((dates[t] - dates[start + 1]).days, -1.0))
            i = t - 1
            if filt is None or filt(i):
                cash += 1.0
                held = {p[0] for p in pos}
                cand = [j for j in np.where(pkv_[i])[0] if j not in held and not lockv[i, j] and not np.isnan(AO[t, j])]
                cand.sort(key=lambda j: -SC_[i, j])
                pick = cand[:N]
                if pick:
                    amt = cash / len(pick)
                    for j in pick:
                        pos.append([j, amt * (1 - BUY) / AO[t, j], t, i])
                    cash = 0.0
            else:
                idx_u += (1.0 + cash) / tx[t]
                cash = 0.0
        keep = []
        for p in pos:
            if t >= p[3] + H:
                cash += p[1] * last_close(t, p[0], p[2]) * (1 - SELL)
            else:
                keep.append(p)
        pos = keep
        v = cash + idx_u * tx[t] + sum(p[1] * last_close(t, p[0], p[2]) for p in pos)
        nav[t - start - 1] = v / units if units > 0 else np.nan
    final = cash + idx_u * tx[T - 1] + sum(p[1] * last_close(T - 1, p[0], p[2]) for p in pos)
    flows.append(((dates[T - 1] - dates[start + 1]).days, final))
    return summarize(nav, flows)


res = {"說明": DOC}
for N in (1, 3):
    for fname, filt in (("不加濾網", None), ("濾網 >50%", lambda i: BR[i] > 50)):
        for vname, (pkv_, SC_) in VER.items():
            rows = []
            for k in range(10):
                entry = {ts[k] for ts in months_of.values() if len(ts) > k}
                o = run2(pkv_, SC_, entry, N=N, filt=filt)
                rows.append(o)
            irr = [r["irr"] for r in rows]
            mdd = [r["mdd"] for r in rows]
            key = f"{N}檔｜{fname}｜{vname}"
            res[key] = {"資金加權年化（第1～10個交易日進場）": irr, "中位數": float(np.median(irr)), "最大回檔中位數": float(np.median(mdd)),
                        "最大回檔": mdd}
            print(key, "年化", irr, "中位", np.median(irr), "回檔中位", np.median(mdd), f"[{time.time() - t0:.0f}s]", flush=True)
idx_rows = []
for k in range(10):
    entry = {ts[k] for ts in months_of.values() if len(ts) > k}
    idx_rows.append(run2(VER["第8版"][0], VER["第8版"][1], entry, filt=lambda i: False)["irr"])
res["加權定期定額（第1～10個交易日）"] = idx_rows
print("加權", idx_rows)
json.dump(res, open("out/monthly_check.json", "w"), ensure_ascii=False, indent=1)
print("完成", f"[{time.time() - t0:.0f}s]")
