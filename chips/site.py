"""把 data/picks 的結果整理成網頁資料，嵌進 site/template.html，輸出 docs/index.html。"""
import json
import os

from . import store
from .model import BENCH, Q_CLOSE, Q_EXR, Q_MKT, Q_OPEN, Q_VOL, Q_DIFF

TEMPLATE = os.path.join(store.ROOT, "site", "template.html")
DOCS = os.path.join(store.ROOT, "docs")


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _day_ret(q):
    """一天的報酬。一般用漲跌價差（對參考價，已扣除權息）；證交所除權息日的漲跌欄是 0，改用當天開盤到收盤。"""
    if not q or q[Q_CLOSE] is None:
        return None
    close, diff, opn = q[Q_CLOSE], q[Q_DIFF], q[Q_OPEN]
    if q[Q_EXR]:
        return close / opn - 1 if opn else None
    if diff is None or close == diff:
        return None
    return diff / (close - diff)


def _hold(code, after, exf, k):
    """名單公布隔天開盤買進、持有到第 k 個交易日收盤的報酬（%）。隔天沒有開盤價（停牌等）回傳 None。"""
    q1 = exf(after[0])["q"].get(code)
    if not q1 or not q1[Q_OPEN] or q1[Q_CLOSE] is None:
        return None
    v = q1[Q_CLOSE] / q1[Q_OPEN]
    for d in after[1:k]:
        r = _day_ret(exf(d)["q"].get(code))
        if r is not None:
            v *= 1 + r
    return round((v - 1) * 100, 2)


def _universe(d, stored, exf, cfg):
    """選股日 d 通過流動性門檻的股票（同市場等權比較的對象）。"""
    i = stored.index(d)
    win = [exf(x) for x in stored[max(0, i - cfg["lookback_days"] + 1):i + 1]]
    out = {mk: [] for mk in BENCH}
    for code, q in exf(d)["q"].items():
        if q[Q_CLOSE] is None or not q[Q_VOL] or q[Q_CLOSE] < cfg["min_price"] or q[Q_MKT] not in out:
            continue
        vols = [e["q"][code][Q_VOL] / 1000 for e in win if code in e["q"] and e["q"][code][Q_VOL]]
        if vols and sum(vols) / len(vols) >= cfg["min_avg_lots"]:
            out[q[Q_MKT]].append(code)
    return out


def history(cfg):
    """之前的名單：隔天開盤買進後 5 日、20 日（以及到最新收盤）的報酬，和同市場合格股票等權平均比較。"""
    dates = store.picks_dates()[:cfg["history_days"]]
    stored = sorted(store.daily_dates())  # 舊到新
    if not stored:
        return []
    cache = {}

    def exf(d):
        if d not in cache:
            cache[d] = store.load_daily(d)
        return cache[d]

    out = []
    for d in dates:
        doc = store.load_picks(d)
        after = [x for x in stored if x > d]
        n = len(after)
        rows = []
        for p in doc["picks"]:
            r = {"code": p["code"], "name": p["name"], "market": p["market"], "sector": p.get("sector"),
                 "rank": p["rank"], "score": p["score"], "close": p["close"], "tags": p.get("tags", [])}
            if n:
                r["entry"] = (exf(after[0])["q"].get(p["code"]) or [None] * 10)[Q_OPEN]
                r["retNow"] = _hold(p["code"], after, exf, n)
                r["ret5"] = _hold(p["code"], after, exf, 5) if n >= 5 else None
                r["ret20"] = _hold(p["code"], after, exf, 20) if n >= 20 else None
            rows.append(r)
        summary = {}
        uni = _universe(d, stored, exf, cfg) if n and d in stored else {mk: [] for mk in BENCH}
        for mk in BENCH:
            grp = [r for r in rows if r["market"] == mk]
            s = {"n": len(grp), "days": n}
            for key, k in (("Now", n), ("5", 5), ("20", 20)):
                if n and n >= k:
                    b = _avg(_hold(c, after, exf, k) for c in uni[mk])
                    rets = [r["ret" + key] for r in grp if r.get("ret" + key) is not None]
                    s["avg" + key], s["bench" + key] = _avg(rets), b
                    s["beat" + key] = round(sum(1 for x in rets if b is not None and x > b) / len(rets) * 100) if rets and b is not None else None
            summary[mk] = s
        out.append({"date": doc["date"], "next": after[0].isoformat() if n else None, "days": n,
                    "latest": stored[-1].isoformat(), "model": doc.get("model"), "summary": summary, "picks": rows})
    return out


def build(cfg, now):
    dates = store.picks_dates()
    if not dates:
        print("還沒有任何選股結果，略過網頁")
        return
    latest = store.load_picks(dates[0])
    # 用名單實際算出的時間，資料沒變時網頁也一字不變，就不會每次都產生新的 commit
    stamp = (latest.get("generatedAt") or now.isoformat(timespec="minutes"))[:16].replace("T", " ")
    data = {
        "site": cfg["site"],
        "generatedAt": stamp,
        "latest": latest,
        "history": history(cfg),
        "backtest": cfg.get("backtest"),
    }
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", payload).replace("__TITLE__", cfg["site"]["title"])
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(DOCS, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)
    # GitHub Pages 不要用 Jekyll 處理，直接照檔案輸出
    open(os.path.join(DOCS, ".nojekyll"), "w").close()
    print("網頁：docs/index.html")
