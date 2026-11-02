"""十年資料上，比較幾種賣出規則（看「跌出前 80 名」是不是只在最近兩年好）。"""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, ".")
exec(open("long_setup.py", encoding="utf-8").read())


def run(rank_lim, hold):
    rows = []
    for i, j, m in trades:
        e = i + 1
        px = AO[e, j]
        if np.isnan(px) or np.isnan(AC[i, j]) or lock[i, j]:
            continue
        x, out, at_open = None, None, False
        for t in range(e, min(i + hold, T - 2) + 1):
            if np.isnan(AC[t, j]):
                continue
            if rank_lim and not RK[t, j] <= rank_lim and t < i + hold:
                x, at_open = t + 1, True
                out = AO[x, j] if not np.isnan(AO[x, j]) else AC[t, j]
                break
        if x is None:
            x = i + hold
            out = last_close(x, j, e)
        g = out / px - 1
        rows.append((dates[i].year, g - COST, g - bench(m, e, x, at_open), x - i))
    a = pd.DataFrame(rows, columns=["y", "net", "exc", "days"])
    per = lambda d, c: d[c].mean() / d.days.mean() * 20 * 100  # noqa: E731
    old, new = a[a.y <= 2023], a[a.y >= 2024]
    return {"平均持有": round(a.days.mean(), 1), "每20日淨%": round(per(a, "net"), 2), "每20日超額%": round(per(a, "exc"), 2),
            "勝率%": round((a.net > 0).mean() * 100), "2014～2023 超額%": round(per(old, "exc"), 2), "2024 以後超額%": round(per(new, "exc"), 2)}


res = []
for name, rl, h in [("固定抱 5 天", None, 5), ("固定抱 20 天", None, 20), ("固定抱 60 天", None, 60),
                    ("跌出前 40 名就賣", 40, 60), ("跌出前 80 名就賣（現行）", 80, 60), ("跌出前 150 名就賣", 150, 60)]:
    res.append(dict(規則=name, **run(rl, h)))
    print(res[-1], flush=True)
pd.set_option("display.width", 200)
print(pd.DataFrame(res).to_string(index=False))
pd.DataFrame(res).to_csv("out/long_rules.csv", index=False)
