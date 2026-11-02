"""用 long_setup 的資料跑現行規則，輸出每筆交易（給後續分析）。先用 2 年資料確認跟 price_rules.py 的結果一樣。"""
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
t0 = time.time()
exec(open("long_setup.py", encoding="utf-8").read())
print(f"準備完成 {time.time() - t0:.0f}s", flush=True)
rows = []
for i, j, m in trades:
    e = i + 1
    px = AO[e, j]
    if np.isnan(px) or np.isnan(AC[i, j]) or lock[i, j]:
        continue
    x, out, at_open = None, None, False
    for t in range(e, min(i + MAXH, T - 2) + 1):
        if np.isnan(AC[t, j]):
            continue
        if not RK[t, j] <= 80 and t < i + MAXH:
            x, at_open = t + 1, True
            out = AO[x, j] if not np.isnan(AO[x, j]) else AC[t, j]
            break
    if x is None:
        x = i + MAXH
        out = last_close(x, j, e)
    g = out / px - 1
    rows.append((dates[i], m, cols[j], g - COST, g - bench(m, e, x, at_open), x - i))
a = pd.DataFrame(rows, columns=["date", "mkt", "code", "net", "exc", "days"])
a.to_pickle(sys.argv[1] if len(sys.argv) > 1 else "out/long_trades.pkl")
per = lambda v, d: v.mean() / d.mean() * 20 * 100  # noqa: E731
print(f"{len(a)} 筆；每20日淨 {per(a.net, a.days):.2f}% 超額 {per(a.exc, a.days):.2f}% 勝率 {(a.net > 0).mean():.0%} 平均持有 {a.days.mean():.1f}；{time.time() - t0:.0f}s")
