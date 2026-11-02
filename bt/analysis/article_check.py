"""對照市場先生〈回測是什麼〉的檢查項目：現行規則（跌出前 80 名就賣）的
每季表現、獲利是否集中在少數交易、盈虧比、大盤在季線上下的表現。"""
import numpy as np
import pandas as pd

src = open("price_rules.py", encoding="utf-8").read()
exec(src[:src.index("plan = [")])  # 共用資料準備、bench、last_close、trades

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
    rows.append((dates[i], m, g - COST, g - bench(m, e, x, at_open), x - i))
a = pd.DataFrame(rows, columns=["date", "mkt", "net", "exc", "days"])
per20 = lambda d: d.net.mean() / d.days.mean() * 20 * 100  # noqa: E731
perx = lambda d: d.exc.mean() / d.days.mean() * 20 * 100  # noqa: E731
print("交易筆數", len(a), "期間", a.date.min().date(), "～", a.date.max().date())
print(f"全部：每20日淨 {per20(a):.2f}% 超額 {perx(a):.2f}% 勝率 {(a.net > 0).mean():.0%}")
w, l = a.net[a.net > 0], a.net[a.net <= 0]
print(f"盈虧比（平均賺 ÷ 平均賠）{w.mean() / -l.mean():.2f}；平均賺 {w.mean()*100:.1f}% 平均賠 {l.mean()*100:.1f}%")
s = a.net.sort_values(ascending=False)
tot = a.net.sum()
for q in (0.01, 0.05):
    k = int(len(s) * q)
    rest = s.iloc[k:]
    print(f"拿掉最好的 {q:.0%}（{k} 筆）：剩下每筆淨 {rest.mean()*100:.2f}%（全部 {a.net.mean()*100:.2f}%），最好那些佔總淨利 {s.iloc[:k].sum()/tot:.0%}")
a["q"] = a.date.dt.to_period("Q").astype(str)
print("\n每季（依名單日期）：")
g = a.groupby("q").apply(lambda d: pd.Series({"筆數": len(d), "每20日淨%": round(per20(d), 2), "每20日超額%": round(perx(d), 2),
                                             "勝率%": round((d.net > 0).mean() * 100)}))
print(g.to_string())
reg = pd.read_csv("out/regime.csv", index_col=0, parse_dates=True)["加權在季線上"]
a["up"] = a.date.map(reg)
print("\n名單那天加權在季線上／下：")
for k, d in a.groupby("up"):
    print("  季線上" if k else "  季線下", len(d), f"每20日淨 {per20(d):.2f}% 超額 {perx(d):.2f}% 勝率 {(d.net > 0).mean():.0%}")
