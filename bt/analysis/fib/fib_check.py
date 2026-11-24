"""驗證 Threads（michael_icwang，2026-11-24）的費氏回撤說法：
「若反彈只到 0.382，後面偏續跌；若能到 0.500，後面偏震盪；若能到 0.618，那才有機會走出上升趨勢。」

資料：bt/vix_hist（Yahoo 日線收盤：加權 1997/7 起、S&P 500 1985 起、那斯達克 1985 起），不含股息。
加權另外補 2026/11/23 收盤 36,811.89（網站資料）、11/24 收盤 40,122.35（新聞，網站當時還沒更新）。

做法（只用當時看得到的資訊）：
- 收盤從高點 H 跌超過 D（20%，另跑 15%）算一段跌勢；L＝H 之後到當天的最低收盤；反彈比例 r＝(收盤−L)/(H−L)。
- 每次收盤創新低，就從新的 L 重新算一段反彈。
- 反彈途中出現新的高點、又從那裡跌超過 D 但沒破 L（例如 2007→2008），當成新的一段跌勢，H 換成那個高點。
- 對每個 k（0.236、0.3、0.382、0.45、0.5、0.55、0.618、0.7、0.786），看反彈第一次收盤碰到 k 之後：
  最後是先回到 H（創新高）、先跌破 L（再破底），還是又出現一段新的跌勢（沒破底）；另看 6、12 個月內先發生哪個。
- 對照：價格純隨機、沒有任何壓力位時，碰到 k 之後先回到 H 的機率約為 ln(碰到的價/L)/ln(H/L)。
從 repo 根目錄執行：python3 bt/analysis/fib/fib_check.py → bt/analysis/fib/out/fib_check.json"""
import json
import os

import numpy as np
import pandas as pd

KS = [0.236, 0.3, 0.382, 0.45, 0.5, 0.55, 0.618, 0.7, 0.786]
HERE = os.path.dirname(os.path.abspath(__file__))


def load(sym):
    rows = json.load(open(os.path.join(HERE, "..", "..", "vix_hist", f"{sym}.json")))
    s = pd.Series({d: c for d, c in rows})
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    if sym == "TWII":
        s.loc[pd.Timestamp("2026-11-23")] = 36811.89
        s.loc[pd.Timestamp("2026-11-24")] = 40122.35
        s = s.sort_index()
    return s


def rebounds(s, D):
    p = s.values
    n = len(p)
    out = []
    H, Hi, ep, eid = p[0], 0, False, 0
    for t in range(n):
        x = p[t]
        if not ep:
            if x > H:
                H, Hi = x, t
            elif x <= H * (1 - D):
                ep, eid = True, eid + 1
                L, Li, RH, RHi, rmax, touch = x, t, x, t, 0, {}
            continue
        if x < L:
            if rmax > 0:
                out.append(dict(ep=eid, H=H, Hi=Hi, L=L, Li=Li, rmax=rmax, end="low", endi=t, touch=touch))
            L, Li, RH, RHi, rmax, touch = x, t, x, t, 0, {}
            continue
        r = (x - L) / (H - L)
        rmax = max(rmax, r)
        for k in KS:
            if r >= k and k not in touch:
                touch[k] = (t, x)
        if x > RH:
            RH, RHi = x, t
        if x >= H:
            out.append(dict(ep=eid, H=H, Hi=Hi, L=L, Li=Li, rmax=r, end="high", endi=t, touch=touch))
            ep, H, Hi = False, x, t
            continue
        if x <= RH * (1 - D):  # 反彈高點又跌超過 D、沒破 L → 新的一段跌勢
            out.append(dict(ep=eid, H=H, Hi=Hi, L=L, Li=Li, rmax=rmax, end="reset", endi=t, touch=touch))
            eid += 1
            H, Hi, L, Li, RH, RHi, rmax, touch = RH, RHi, x, t, x, t, 0, {}
    if ep and rmax > 0:
        out.append(dict(ep=eid, H=H, Hi=Hi, L=L, Li=Li, rmax=rmax, end="open", endi=n - 1, touch=touch))
    return out, n


def window(rb, ti, n, h, p):
    for t in range(ti + 1, min(ti + h, n - 1) + 1):
        if p[t] >= rb["H"]:
            return "high"
        if p[t] < rb["L"]:
            return "low"
    return "none" if ti + h <= n - 1 else None


def table(items):
    rows = []
    for k in KS:
        ev = {"high": 0, "low": 0, "reset": 0}
        w = {126: {"high": 0, "low": 0, "none": 0}, 252: {"high": 0, "low": 0, "none": 0}}
        base, eps = [], set()
        for rb, n, sym, p in items:
            if k not in rb["touch"]:
                continue
            ti, tx = rb["touch"][k]
            if rb["end"] != "open":
                ev[rb["end"]] += 1
                eps.add((sym, rb["ep"]))
                base.append(np.log(tx / rb["L"]) / np.log(rb["H"] / rb["L"]))
            for h in w:
                o = window(rb, ti, n, h, p)
                if o:
                    w[h][o] += 1
        m = sum(ev.values())
        pc = lambda a, b: round(100 * a / b) if b else None  # noqa: E731
        a6, a12 = sum(w[126].values()), sum(w[252].values())
        rows.append({"k": k, "次數": m, "段數": len(eps),
                     "最後：先創新高%": pc(ev["high"], m), "最後：先再破底%": pc(ev["low"], m), "最後：又一段新跌勢（沒破底）%": pc(ev["reset"], m),
                     "純隨機對照：先創新高%": round(100 * np.mean(base)) if base else None,
                     "6個月內：創新高%": pc(w[126]["high"], a6), "6個月內：再破底%": pc(w[126]["low"], a6), "6個月內：都沒有%": pc(w[126]["none"], a6),
                     "12個月內：創新高%": pc(w[252]["high"], a12), "12個月內：再破底%": pc(w[252]["low"], a12), "12個月內：都沒有%": pc(w[252]["none"], a12)})
    return rows


res = {"說明": __doc__}
for D in (0.20, 0.15):
    items = []
    for sym in ("TWII", "GSPC", "IXIC"):
        s = load(sym)
        rb, n = rebounds(s, D)
        its = [(r, n, sym, s.values) for r in rb]
        items += its
        res[f"D={int(D * 100)}% {sym}"] = table(its)
        if sym == "TWII":
            res[f"D={int(D * 100)}% 加權每段跌勢（反彈最高 0.236 以上）：低點日、低點、反彈最高比例、結果、結束日"] = {
                f"{s.index[r['Hi']].date()} 高點 {r['H']:.1f}": None for r in rb}
            eps = {}
            for r in rb:
                key = f"{s.index[r['Hi']].date()} 高點 {r['H']:.1f}"
                eps.setdefault(key, [])
                if r["rmax"] >= 0.236:
                    eps[key].append([str(s.index[r["Li"]].date()), round(float(r["L"]), 1), round(float(r["rmax"]), 3), r["end"], str(s.index[r["endi"]].date())])
            res[f"D={int(D * 100)}% 加權每段跌勢（反彈最高 0.236 以上）：低點日、低點、反彈最高比例、結果、結束日"] = eps
            if D == 0.20 and rb and rb[-1]["end"] == "open":
                c = rb[-1]
                res["加權現在（收盤算）"] = {"H": [str(s.index[c["Hi"]].date()), round(float(c["H"]), 2)], "L": [str(s.index[c["Li"]].date()), round(float(c["L"]), 2)],
                                     "最新收盤": [str(s.index[-1].date()), float(s.iloc[-1])], "反彈比例": round(float((s.iloc[-1] - c["L"]) / (c["H"] - c["L"])), 3)}
    res[f"D={int(D * 100)}% 三個市場合計"] = table(items)
# 貼文圖上的價位（盤中高低點）核對
Hc, Lc = 49966.89, 35527.69
res["貼文圖上的價位核對（H 49,966.89、L 35,527.69）"] = {str(k): round(Lc + k * (Hc - Lc), 2) for k in (0.236, 0.382, 0.5, 0.618, 0.786)}
res["貼文圖上的價位核對（L 改用新聞的 11/23 盤中低點 35,442.41）"] = {str(k): round(35442.41 + k * (Hc - 35442.41), 2) for k in (0.382, 0.5, 0.618)}
res["11/24 收盤在貼文圖的反彈比例"] = round((40122.35 - Lc) / (Hc - Lc), 3)
os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
json.dump(res, open(os.path.join(HERE, "out", "fib_check.json"), "w"), ensure_ascii=False, indent=1)
for k, v in res.items():
    if k == "說明":
        continue
    print("==", k)
    if isinstance(v, list):
        for r in v:
            print(" ", list(r.values()))
    elif isinstance(v, dict):
        for a, b in v.items():
            print(" ", a, b)
    else:
        print(" ", v)
