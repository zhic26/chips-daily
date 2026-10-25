"""籌碼評分、大盤體溫與各種排行。輸入是 data/daily 的每日盤後資料，輸出是一天的結果。"""
from .sources import INDUSTRY

MODEL_VERSION = 3  # 計分方式改版時加一，舊的名單會在下次執行時用新方式重算
LOT = 1000
MARKETS = ("上市", "上櫃")
INDEX_ORDER = ["加權指數", "櫃買指數", "半導體", "電子", "金融", "航運", "生技"]
BENCH = {"上市": "加權指數", "上櫃": "櫃買指數"}

# daily 檔案裡 q（行情）陣列的欄位位置
Q_NAME, Q_MKT, Q_CLOSE, Q_DIFF, Q_OPEN, Q_HIGH, Q_LOW, Q_VOL, Q_AMT, Q_EXR = range(10)


def pct_rank(values):
    """每個值在清單中的百分位（0～1），同分取平均名次。"""
    n = len(values)
    if n <= 1:
        return [0.5] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 / (n - 1)
        i = j + 1
    return ranks


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def sector_of(code, companies):
    return INDUSTRY.get((companies.get(code) or {}).get("industry", ""), "其他")


def _inst(ex, code):
    return ex["inst"].get(code) or [0, 0, 0, 0]


def _streak(series):
    n = 0
    for v in series:  # 新到舊
        if v > 0:
            n += 1
        else:
            break
    return n


def _chg_pct(close, diff):
    if close is None or diff is None or close == diff:
        return 0.0
    return round(diff / (close - diff) * 100, 2)


def _sum(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs), 1) if xs else None


class History:
    """近 N 個交易日的收盤價與大盤統計（季線、20 日漲幅、量能與融資趨勢用）。days 為新到舊。"""

    def __init__(self, days, exs):
        self.days = days
        self.idx = {d: i for i, d in enumerate(days)}
        n = len(days)
        self.close, self.mk = {}, {}
        for i, d in enumerate(days):
            for code, q in exs[d]["q"].items():
                if q[Q_CLOSE] is None:
                    continue
                arr = self.close.get(code)
                if arr is None:
                    arr = self.close[code] = [None] * n
                    self.mk[code] = q[Q_MKT]
                arr[i] = q[Q_CLOSE]
        self.market = {d: dict(exs[d].get("market") or {}, flows=exs[d].get("flows"),
                               indices=exs[d].get("indices") or {}) for d in days}
        self._breadth = {}

    def closes(self, code, d, n):
        arr = self.close.get(code)
        i = self.idx.get(d)
        return arr[i:i + n] if arr and i is not None else []

    def breadth(self, d, mk):
        """站上季線（收盤 > 60 日均價）的股票比例 %。歷史不足 60 天回傳 None。"""
        key = (d, mk)
        if key not in self._breadth:
            i = self.idx[d]
            val = None
            if i + 60 <= len(self.days):
                above = total = 0
                for code, arr in self.close.items():
                    if self.mk.get(code) != mk or arr[i] is None:
                        continue
                    win = [v for v in arr[i:i + 60] if v is not None]
                    if len(win) < 55:
                        continue
                    total += 1
                    if arr[i] > sum(win) / len(win):
                        above += 1
                val = round(above / total * 100, 1) if total >= 50 else None
            self._breadth[key] = val
        return self._breadth[key]


def stock_rows(days, exs, cfg, companies, history):
    """days：新到舊的完整資料交易日，第一天是選股日。回傳通過流動性門檻的股票（含各項原始指標）。"""
    L = cfg["lookback_days"]
    window = days[:L]
    d0 = days[0]
    e0 = exs[d0]
    rows = []
    for code, q in e0["q"].items():
        close, vol = q[Q_CLOSE], q[Q_VOL]
        if close is None or not vol:
            continue
        vols = [exs[x]["q"][code][Q_VOL] / LOT for x in window if code in exs[x]["q"] and exs[x]["q"][code][Q_VOL]]
        avg = sum(vols) / len(vols)
        if avg < cfg["min_avg_lots"] or close < cfg["min_price"]:
            continue
        inst_hist = [_inst(exs[x], code)[3] / LOT for x in window]
        f_all = [_inst(exs[x], code)[0] for x in days]
        t_all = [_inst(exs[x], code)[1] for x in days]
        fi, it, dl, tot = _inst(e0, code)
        m = e0["margin"].get(code)
        # 籌碼偏重的兩個訊號：融資 5 日增幅、20 日漲幅；另外附上季線乖離給明細用
        ms = [exs[x]["margin"].get(code) for x in window]
        margin_up5 = margin_add5 = None
        if all(ms):
            margin_add5 = sum(v[1] for v in ms)
            base = ms[0][0] - margin_add5
            margin_up5 = round(margin_add5 / base * 100, 1) if base > 0 else None
        cl = history.closes(code, d0, 61)
        ret20 = round((close / cl[20] - 1) * 100, 1) if len(cl) > 20 and cl[20] else None
        win60 = [v for v in cl[:60] if v is not None]
        ma60 = sum(win60) / len(win60) if len(win60) >= 55 else None
        rows.append({
            "code": code, "name": q[Q_NAME], "market": q[Q_MKT], "sector": sector_of(code, companies),
            "close": close, "chgPct": _chg_pct(close, q[Q_DIFF]), "volume": round(vol / LOT), "avgVol": round(avg),
            "foreignNet": round(fi / LOT), "trustNet": round(it / LOT), "dealerNet": round(dl / LOT),
            "instNet": round(tot / LOT), "instHist": [round(x) for x in inst_hist], "inst5d": round(sum(inst_hist)),
            "foreignDays": sum(1 for v in f_all[:L] if v > 0), "trustDays": sum(1 for v in t_all[:L] if v > 0),
            "foreignStreak": _streak(f_all), "trustStreak": _streak(t_all),
            "marginChg": round(m[1]) if m else None, "marginBal": round(m[0]) if m else None,
            "marginAdd5": round(margin_add5) if margin_add5 is not None else None, "marginUp5": margin_up5,
            "ret20": ret20, "ma60": round(ma60, 2) if ma60 else None,
            "bias60": round((close / ma60 - 1) * 100, 1) if ma60 else None,
            "series": [exs[x]["q"].get(code, [None] * 10)[Q_CLOSE] for x in reversed(window)],
            "_avg": avg, "_n": len(window),
        })
    return rows


def crowding(x, c):
    """籌碼偏重扣分：(扣幾分, [原因])。"""
    pts, why = 0, []
    lo, hi = c["points"]
    mu, add = x.get("marginUp5"), x.get("marginAdd5") or 0
    if mu is not None and add >= c.get("margin_min_lots", 300):
        p = hi if mu >= c["margin_5d_pct"][1] else lo if mu >= c["margin_5d_pct"][0] else 0
        if p:
            pts += p
            why.append(f"融資 5 日增加 {mu:.0f}%（{add:,} 張）")
    ru = x.get("ret20")
    if ru is not None:
        p = hi if ru >= c["runup_20d_pct"][1] else lo if ru >= c["runup_20d_pct"][0] else 0
        if p:
            pts += p
            why.append(f"近 20 日已漲 {ru:.0f}%")
    return min(pts, c["max_penalty"]), why


def weights_for(cfg, margin_ok):
    w = dict(cfg["weights"])
    if not margin_ok:  # 融資資料還沒公布：這一項不計分，其他項目依比例放大回滿分 100
        rest = sum(v for k, v in w.items() if k != "margin")
        w = {k: (0 if k == "margin" else v * 100 / rest) for k, v in w.items()}
    return w


def score_market(rows, w, big_lookup, cfg):
    """big_lookup(codes) -> {code: (bigPct, bigChg)}；只對需要的股票查（逐檔查詢很慢）。"""
    if not rows:
        return []
    r1 = pct_rank([x["instNet"] / x["_avg"] for x in rows])
    r5 = pct_rank([x["inst5d"] / (x["_avg"] * x["_n"]) for x in rows])
    rc = pct_rank([x["foreignDays"] + 1.5 * x["trustDays"] for x in rows])
    rm = pct_rank([-(x["marginAdd5"] if x["marginAdd5"] is not None else 0) / x["_avg"] for x in rows])
    for x, a, b, c, m in zip(rows, r1, r5, rc, rm):
        x["parts"] = {"inst_today": a * w["inst_today"], "inst_5d": b * w["inst_5d"],
                      "consistency": c * w["consistency"], "margin": m * w["margin"], "big_holders": 0.0}
        pts, x["crowd"] = crowding(x, cfg["crowding"])
        x["penalty"] = pts if cfg["crowding"].get("deduct") else 0
        x["_pre"] = sum(x["parts"].values()) - x["penalty"]
    pool = [x for x in rows if x["instNet"] > 0]  # 當天三大法人必須是買超
    if big_lookup.full:
        cands = pool
    else:
        cands = sorted(pool, key=lambda x: -x["_pre"])[:cfg["tdcc_candidates"]]
    info = big_lookup([x["code"] for x in cands])
    out = []
    for x in cands:
        pct, chg = info.get(x["code"], (None, None))
        x["bigPct"], x["bigChg"] = pct, chg
        if pct is not None and pct >= cfg["max_big_pct"]:
            continue  # 千張大戶持股 99% 以上（多為公開收購或合併），幾乎沒有流通籌碼
        x["parts"]["big_holders"] = clamp(((chg if chg is not None else 0) + 1) / 2) * w["big_holders"]
        x["parts"] = {k: round(v, 1) for k, v in x["parts"].items()}
        x["score"] = round(max(0, sum(x["parts"].values()) - x["penalty"]), 1)
        out.append(x)
    out.sort(key=lambda x: (-x["score"], -x["instNet"]))
    return out[:cfg["top_n"]]


def tags_for(x):
    t = []
    if x.get("crowd"):
        t.append(f"籌碼偏重 −{x['penalty']}" if x.get("penalty") else "籌碼偏重")
    if x["trustStreak"] >= 3:
        t.append(f"投信連買 {x['trustStreak']} 日")
    if x["foreignStreak"] >= 3:
        t.append(f"外資連買 {x['foreignStreak']} 日")
    if x.get("bigChg") is not None and x["bigChg"] >= 0.5:
        t.append("大戶增持")
    if x.get("marginAdd5") is not None and -x["marginAdd5"] >= x["avgVol"] * 0.1:
        t.append("融資大減")
    if x["inst5d"] > x["avgVol"]:
        t.append("5 日買超大於均量")
    if x["chgPct"] >= 9.5:
        t.append("漲停")
    return t


def reason_for(x):
    s = [f"三大法人買超 {x['instNet']:,} 張（外資 {x['foreignNet']:+,}、投信 {x['trustNet']:+,}、自營 {x['dealerNet']:+,}）",
         f"近 5 日累計 {x['inst5d']:+,} 張，約 5 日均量的 {x['inst5d'] / max(1, x['avgVol']):.1f} 倍"]
    if x.get("bigPct") is not None:
        t = f"千張大戶持股 {x['bigPct']:.2f}%"
        if x.get("bigChg") is not None:
            t += f"，較前一週{'增加' if x['bigChg'] >= 0 else '減少'} {abs(x['bigChg']):.2f} 個百分點"
        s.append(t)
    if x.get("marginAdd5"):
        s.append(f"融資近 5 日{'減少' if x['marginAdd5'] < 0 else '增加'} {abs(x['marginAdd5']):,} 張")
    if x.get("crowd"):
        s.append(("籌碼偏重扣 " + str(x["penalty"]) + " 分：" if x.get("penalty") else "籌碼偏重：") + "、".join(x["crowd"]))
    return "；".join(s).replace("-", "−") + "。"


def rankings(days, exs, cfg, companies, pick_codes):
    """成交量、週轉率（上市、上櫃各前 N）與當沖熱度（合併前 N）。"""
    n = cfg["top_n"]
    e0 = exs[days[0]]
    base = []
    for code, q in e0["q"].items():
        close, vol = q[Q_CLOSE], q[Q_VOL]
        if close is None or not vol:
            continue
        sh = e0["shares"].get(code)
        base.append({"code": code, "name": q[Q_NAME], "market": q[Q_MKT], "sector": sector_of(code, companies),
                     "close": close, "chgPct": _chg_pct(close, q[Q_DIFF]), "volume": round(vol / LOT),
                     "value": round(q[Q_AMT] / 1e8, 2), "turnover": round(vol / sh * 100, 2) if sh else None,
                     "inPicks": code in pick_codes, "_q": q})
    out = {"volume": {}, "turnover": {}}
    for mk in MARKETS:
        grp = [x for x in base if x["market"] == mk]
        out["volume"][mk] = sorted(grp, key=lambda x: -x["volume"])[:n]
        out["turnover"][mk] = sorted((x for x in grp if x["turnover"] is not None), key=lambda x: -x["turnover"])[:n]
    hot = []
    prev = days[1:5]
    for x in base:
        d = e0["dt"].get(x["code"])
        if not d or x["volume"] < cfg["daytrade_min_lots"] or x["close"] < cfg["min_price"]:
            continue
        pv = [exs[p]["q"][x["code"]][Q_VOL] / LOT for p in prev if x["code"] in exs[p]["q"] and exs[p]["q"][x["code"]][Q_VOL]]
        q = x["_q"]
        hi, lo = q[Q_HIGH] or 0, q[Q_LOW] or 0
        hot.append(dict(x, dtRatio=round(d[0] / q[Q_VOL] * 100, 1),
                        surge=round(x["volume"] / (sum(pv) / len(pv)), 2) if pv else None,
                        pos=round((x["close"] - lo) / (hi - lo), 2) if hi > lo else None,
                        instNet=round(_inst(e0, x["code"])[3] / LOT), shortFirst=not d[1]))
    out["daytrade"] = sorted(hot, key=lambda x: (-x["dtRatio"], -x["volume"]))[:n]
    for lst in (out["volume"], out["turnover"]):
        for mk in lst:
            lst[mk] = [{k: v for k, v in x.items() if not k.startswith("_")} for x in lst[mk]]
    out["daytrade"] = [{k: v for k, v in x.items() if not k.startswith("_")} for x in out["daytrade"]]
    return out


def market_temp(d0, exs, history):
    """大盤體溫：量能、融資、法人金額、站上季線比例、漲跌家數，以及近 20 日走勢。全部是描述，不是建議。"""
    H = history
    days = H.days[H.idx[d0]:]
    m = lambda d, k: H.market[d].get(k)
    yi = lambda v, div=1e8, nd=1: round(v / div, nd) if v is not None else None

    vals = [m(d, "value") for d in days[:21]]
    prev = [v for v in vals[1:21] if v]
    avg20 = sum(prev) / len(prev) if prev else None
    today_v = vals[0] if vals else None
    ratio = round(today_v / avg20, 3) if today_v and avg20 else None

    def margin_chg(d):
        a, p = m(d, "marginAmt"), m(d, "marginAmtPrev")
        return round((a - p) / 1e5, 1) if a is not None and p is not None else None  # 仟元 → 億元

    mchg = [margin_chg(d) for d in days[:20]]

    def flow(d, k):
        f = m(d, "flows") or {}
        return yi(f.get(k))

    fser = [flow(d, "外資") for d in days[:20]]
    tser = [flow(d, "投信") for d in days[:20]]
    breadth = {}
    for mk in MARKETS:
        ser = [H.breadth(d, mk) for d in days[:20]]
        breadth[mk] = {"pct": ser[0], "prev5": ser[5] if len(ser) > 5 else None, "series": list(reversed(ser))}
    adv = {}
    for mk in MARKETS:
        up = dn = flat = 0
        for q in exs[d0]["q"].values():
            if q[Q_MKT] != mk or q[Q_CLOSE] is None or not q[Q_VOL]:
                continue
            diff = q[Q_DIFF] or 0
            up, dn, flat = up + (diff > 0), dn + (diff < 0), flat + (diff == 0)
        adv[mk] = {"up": up, "down": dn, "flat": flat}

    taiex = (exs[d0].get("indices") or {}).get("加權指數") or {}
    out = {
        "dates": [d.isoformat() for d in reversed(days[:20])],
        "value": {"today": yi(today_v, nd=0), "avg20": yi(avg20, nd=0), "ratio": ratio,
                  "series": [yi(v, nd=0) for v in reversed(vals[:20])]},
        "margin": {"chg": mchg[0] if mchg else None, "chg5": _sum(mchg[:5]),
                   "bal": yi(m(d0, "marginAmt"), 1e5, 0), "series": list(reversed(mchg))},
        "foreign": {"today": fser[0] if fser else None, "sum5": _sum(fser[:5]), "series": list(reversed(fser))},
        "trust": {"today": tser[0] if tser else None, "sum5": _sum(tser[:5]), "series": list(reversed(tser))},
        "breadth": breadth,
        "adv": adv,
        "taiexChg": taiex.get("chgPct"),
    }
    out["read"] = temp_read(out)
    return out


def temp_read(t):
    """把數字寫成幾句描述（不做預測、不給建議）。"""
    read = []
    v, tx = t["value"], t["taiexChg"]
    if v["ratio"]:
        pct = (v["ratio"] - 1) * 100
        s = f"上市成交 {v['today']:,.0f} 億，" + (f"比 20 日均量少 {abs(pct):.0f}%" if pct <= -3 else
                                               f"比 20 日均量多 {pct:.0f}%" if pct >= 3 else "和 20 日均量差不多")
        if tx is not None:
            if tx > 0 and pct <= -10:
                s += "；指數上漲但量縮，買盤承接還不明確"
            elif tx < 0 and pct >= 10:
                s += "；放量下跌，賣壓較重"
            elif tx > 0 and pct >= 10:
                s += "；價漲量增"
            elif tx < 0 and pct <= -10:
                s += "；量縮下跌"
        read.append(s + "。")
    mg = t["margin"]
    if mg["chg"] is not None:
        s = f"融資{'減少' if mg['chg'] < 0 else '增加'} {abs(mg['chg']):.1f} 億"
        if mg["chg5"] is not None:
            s += f"，近 5 日累計{'減少' if mg['chg5'] < 0 else '增加'} {abs(mg['chg5']):.1f} 億"
        read.append(s + "。")
    b = t["breadth"]["上市"]
    if b["pct"] is not None:
        s = f"上市站上季線的股票占 {b['pct']:.0f}%"
        if b["prev5"] is not None:
            s += f"（5 個交易日前 {b['prev5']:.0f}%）"
        if b["pct"] < 30:
            s += "，多數股票還在季線下"
        elif b["pct"] > 70:
            s += "，多數股票在季線上"
        read.append(s + "。")
    return read


def compute_day(days, exs, cfg, companies, big_provider, history):
    """計算 days[0] 這一天的選股、排行與大盤體溫。days：新到舊的完整資料交易日。"""
    d0 = days[0]
    e0 = exs[d0]
    rows = stock_rows(days, exs, cfg, companies, history)
    lookup = big_provider.lookup_for(d0)
    picks = []
    universe, eff = {}, {}
    for mk in MARKETS:
        grp = [x for x in rows if x["market"] == mk]
        universe[mk] = len(grp)
        margin_ok = ("twse_margin" if mk == "上市" else "tpex_margin") not in e0["pending"]
        w = weights_for(cfg, margin_ok)
        eff[mk] = {k: round(v, 1) for k, v in w.items()}
        top = score_market(grp, w, lookup, cfg)
        for i, x in enumerate(top, 1):
            x["rank"] = i
            x["tags"] = tags_for(x)
            x["reason"] = reason_for(x)
            picks.append({k: v for k, v in x.items() if not k.startswith("_")})
    pending_margin = [mk for mk, s in (("上市", "twse_margin"), ("上櫃", "tpex_margin")) if s in e0["pending"]]
    idx = e0.get("indices", {})
    return {
        "model": MODEL_VERSION,
        "date": d0.isoformat(),
        "tradingDays": [x.isoformat() for x in days[:cfg["lookback_days"]]],
        "tdcc": lookup.describe(),
        "marginPending": pending_margin,
        "pending": e0["pending"],
        "universe": universe,
        "weights": cfg["weights"],
        "effectiveWeights": eff,
        "crowding": cfg["crowding"],
        "filters": {k: cfg[k] for k in ("min_avg_lots", "min_price", "lookback_days", "max_big_pct", "top_n",
                                        "daytrade_min_lots")},
        "indices": [dict(idx[k], name=k) for k in INDEX_ORDER if k in idx],
        "flows": e0.get("flows"),
        "temp": market_temp(d0, exs, history),
        "picks": picks,
        "rank": rankings(days, exs, cfg, companies, {p["code"] for p in picks}),
    }
