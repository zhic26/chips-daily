"""籌碼評分與各種排行。輸入是 data/daily 的每日盤後資料，輸出是一天的選股結果。"""
from .sources import INDUSTRY

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


def stock_rows(days, exs, cfg, companies):
    """days：新到舊的交易日，第一天是選股日。回傳通過流動性門檻的股票（含各項原始指標）。"""
    L = cfg["lookback_days"]
    window = days[:L]
    e0 = exs[days[0]]
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
        rows.append({
            "code": code, "name": q[Q_NAME], "market": q[Q_MKT], "sector": sector_of(code, companies),
            "close": close, "chgPct": _chg_pct(close, q[Q_DIFF]), "volume": round(vol / LOT), "avgVol": round(avg),
            "foreignNet": round(fi / LOT), "trustNet": round(it / LOT), "dealerNet": round(dl / LOT),
            "instNet": round(tot / LOT), "instHist": [round(x) for x in inst_hist], "inst5d": round(sum(inst_hist)),
            "foreignDays": sum(1 for v in f_all[:L] if v > 0), "trustDays": sum(1 for v in t_all[:L] if v > 0),
            "foreignStreak": _streak(f_all), "trustStreak": _streak(t_all),
            "marginChg": round(m[1]) if m else None, "marginBal": round(m[0]) if m else None,
            "series": [exs[x]["q"].get(code, [None] * 10)[Q_CLOSE] for x in reversed(window)],
            "_avg": avg, "_n": len(window),
        })
    return rows


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
    rm = pct_rank([-(x["marginChg"] or 0) / x["_avg"] for x in rows])
    for x, a, b, c, m in zip(rows, r1, r5, rc, rm):
        x["parts"] = {"inst_today": a * w["inst_today"], "inst_5d": b * w["inst_5d"],
                      "consistency": c * w["consistency"], "margin": m * w["margin"], "big_holders": 0.0}
        x["_pre"] = sum(x["parts"].values())
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
        x["score"] = round(sum(x["parts"].values()), 1)
        out.append(x)
    out.sort(key=lambda x: (-x["score"], -x["instNet"]))
    return out[:cfg["top_n"]]


def tags_for(x):
    t = []
    if x["trustStreak"] >= 3:
        t.append(f"投信連買 {x['trustStreak']} 日")
    if x["foreignStreak"] >= 3:
        t.append(f"外資連買 {x['foreignStreak']} 日")
    if x.get("bigChg") is not None and x["bigChg"] >= 0.5:
        t.append("大戶增持")
    if x["marginChg"] is not None and -x["marginChg"] >= x["avgVol"] * 0.05:
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
    if x["marginChg"]:
        s.append(f"融資{'減少' if x['marginChg'] < 0 else '增加'} {abs(x['marginChg']):,} 張")
    return "；".join(s) + "。"


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


def compute_day(days, exs, cfg, companies, big_provider):
    """計算 days[0] 這一天的選股結果。"""
    d0 = days[0]
    e0 = exs[d0]
    rows = stock_rows(days, exs, cfg, companies)
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
        "date": d0.isoformat(),
        "tradingDays": [x.isoformat() for x in days[:cfg["lookback_days"]]],
        "tdcc": lookup.describe(),
        "marginPending": pending_margin,
        "pending": e0["pending"],
        "universe": universe,
        "weights": cfg["weights"],
        "effectiveWeights": eff,
        "filters": {k: cfg[k] for k in ("min_avg_lots", "min_price", "lookback_days", "max_big_pct", "top_n",
                                        "daytrade_min_lots")},
        "indices": [dict(idx[k], name=k) for k in INDEX_ORDER if k in idx],
        "flows": e0.get("flows"),
        "picks": picks,
        "rank": rankings(days, exs, cfg, companies, {p["code"] for p in picks}),
    }
