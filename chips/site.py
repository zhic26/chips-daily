"""把 data/picks 的結果整理成網頁資料，嵌進 site/template.html，輸出 docs/index.html。"""
import json
import os

from . import store
from .model import BENCH, Q_CLOSE

TEMPLATE = os.path.join(store.ROOT, "site", "template.html")
DOCS = os.path.join(store.ROOT, "docs")


def _ret(a, b):
    return round((b / a - 1) * 100, 2) if a and b else None


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _win(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(1 for x in xs if x > 0) / len(xs) * 100) if xs else None


def history(cfg):
    """近 N 個交易日的選股名單，加上隔日與至今的漲跌（以選出當天收盤價為基準，未還原除權息）。"""
    dates = store.picks_dates()[:cfg["history_days"]]
    stored = sorted(store.daily_dates())  # 舊到新
    if not stored:
        return []
    latest_day = stored[-1]
    cache = {}

    def ex(d):
        if d not in cache:
            cache[d] = store.load_daily(d)
        return cache[d]

    latest = ex(latest_day)
    out = []
    for d in dates:
        doc = store.load_picks(d)
        nxt = next((x for x in stored if x > d), None)
        e1 = ex(nxt) if nxt else None
        idx0 = {i["name"]: i["close"] for i in doc.get("indices", [])}
        rows = []
        for p in doc["picks"]:
            c0 = p["close"]
            c1 = e1["q"].get(p["code"], [None] * 10)[Q_CLOSE] if e1 else None
            cn = latest["q"].get(p["code"], [None] * 10)[Q_CLOSE] if latest_day > d else None
            rows.append({"code": p["code"], "name": p["name"], "market": p["market"], "sector": p.get("sector"),
                         "rank": p["rank"], "score": p["score"], "close": c0, "tags": p.get("tags", []),
                         "ret1": _ret(c0, c1), "retNow": _ret(c0, cn)})
        summary = {}
        for mk, bench in BENCH.items():
            grp = [r for r in rows if r["market"] == mk]
            b0 = idx0.get(bench)
            b1 = (e1 or {}).get("indices", {}).get(bench, {}).get("close") if e1 else None
            bn = latest.get("indices", {}).get(bench, {}).get("close") if latest_day > d else None
            summary[mk] = {"n": len(grp), "avg1": _avg(r["ret1"] for r in grp), "win1": _win(r["ret1"] for r in grp),
                           "avgNow": _avg(r["retNow"] for r in grp), "winNow": _win(r["retNow"] for r in grp),
                           "bench1": _ret(b0, b1), "benchNow": _ret(b0, bn)}
        out.append({"date": doc["date"], "next": nxt.isoformat() if nxt else None,
                    "latest": latest_day.isoformat(), "summary": summary, "picks": rows})
    return out


def build(cfg, now):
    dates = store.picks_dates()
    if not dates:
        print("還沒有任何選股結果，略過網頁")
        return
    latest = store.load_picks(dates[0])
    data = {
        "site": cfg["site"],
        "generatedAt": now.strftime("%Y-%m-%d %H:%M"),
        "latest": latest,
        "history": history(cfg),
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
