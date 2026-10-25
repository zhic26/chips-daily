"""實盤成績：每天公布的名單，在下一個平日開盤前固定下來，之後模型改版、重算舊名單都不會改；
再追蹤這些名單 5 日、20 日的表現，跟回測比。

存在 data/track/YYYY-MM-DD.json。滿 20 個交易日後把結果也寫進去（final），之後就算每日資料被清掉也還在。
"""
import datetime as dt
import glob
import os

from . import store
from .model import BENCH
from .perf import avg, hold, universe

TPE = dt.timezone(dt.timedelta(hours=8))
DIR = os.path.join(store.DATA, "track")


def lock_at(d):
    """d 的名單在下一個平日早上 9 點開盤後就固定（之前還可以因為晚到的資料更新）。"""
    n = d + dt.timedelta(days=1)
    while n.weekday() >= 5:
        n += dt.timedelta(days=1)
    return dt.datetime(n.year, n.month, n.day, 9, 0, tzinfo=TPE)


def _path(date_iso):
    return os.path.join(store.DATA, "track", f"{date_iso}.json")


def record(doc, now):
    """把剛公布的名單記下來。已經過了固定時間（例如事後補算舊日子）就不記。回傳是否有寫入。"""
    d = dt.date.fromisoformat(doc["date"])
    if now >= lock_at(d):
        return False
    new = {"date": doc["date"], "model": doc["model"],
           "picks": [[p["code"], p["market"], p["rank"], p["score"]] for p in doc["picks"]]}
    old = store._read(_path(doc["date"]))
    if old and {k: old.get(k) for k in new} == new:
        return False
    new["savedAt"] = now.isoformat(timespec="minutes")
    store._write(_path(doc["date"]), new)
    return True


def results(cfg):
    """每份實盤名單的結果（還沒滿 20 天的每次重算，滿了就寫回檔案固定）。舊到新。"""
    files = sorted(glob.glob(os.path.join(store.DATA, "track", "*.json")))
    if not files:
        return []
    stored = sorted(store.daily_dates())
    cache = {}

    def exf(d):
        if d not in cache:
            cache[d] = store.load_daily(d)
        return cache[d]

    out = []
    for f in files:
        t = store._read(f)
        if t.get("final"):
            out.append(t)
            continue
        d = dt.date.fromisoformat(t["date"])
        after = [x for x in stored if x > d]
        n = len(after)
        t["days"] = n
        if n >= 5 and d in stored:
            uni = universe(d, stored, exf, cfg)
            res = {}
            for mk in BENCH:
                codes = [c for c, m, _, _ in t["picks"] if m == mk]
                if not codes:
                    continue
                r = {"n": len(codes)}
                for k in (5, 20):
                    if n >= k:
                        rets = [x for x in (hold(c, after, exf, k) for c in codes) if x is not None]
                        b = avg(hold(c, after, exf, k) for c in uni[mk])
                        r[f"avg{k}"], r[f"bench{k}"] = avg(rets), b
                        r[f"beat{k}"] = round(sum(1 for x in rets if x > b) / len(rets) * 100) if rets and b is not None else None
                res[mk] = r
            t["result"] = res
            if n >= 20:
                t["final"] = True
                store._write(f, t)
        out.append(t)
    return out


def _excess(r, k):
    a, b = r.get(f"avg{k}"), r.get(f"bench{k}")
    return None if a is None or b is None else a - b


def summary(rows, cfg):
    """網頁用的彙總：各市場與合計的平均超額、名單贏過同市場的比例、各模型版本，以及每份名單的超額走勢。"""
    if not rows:
        return {"lists": 0}
    out = {"since": rows[0]["date"], "lists": len(rows), "latest": rows[-1]["date"], "market": {}, "models": [], "series": []}
    for k in (5, 20):
        for mk in BENCH:
            ex = [e for e in (_excess((t.get("result") or {}).get(mk) or {}, k) for t in rows) if e is not None]
            m = out["market"].setdefault(mk, {})
            m[f"n{k}"] = len(ex)
            m[f"ex{k}"] = round(sum(ex) / len(ex), 2) if ex else None
            m[f"win{k}"] = round(sum(1 for e in ex if e > 0) / len(ex) * 100) if ex else None
    by = {}
    for t in rows:
        res = t.get("result") or {}
        e5 = [e for e in (_excess(res.get(mk) or {}, 5) for mk in BENCH) if e is not None]
        e20 = [e for e in (_excess(res.get(mk) or {}, 20) for mk in BENCH) if e is not None]
        row = {"date": t["date"], "model": t["model"], "ex5": round(sum(e5) / len(e5), 2) if e5 else None,
               "ex20": round(sum(e20) / len(e20), 2) if e20 else None}
        out["series"].append(row)
        b = by.setdefault(t["model"], {"model": t["model"], "lists": 0, "from": t["date"], "e5": [], "e20": []})
        b["lists"] += 1
        b["to"] = t["date"]
        if row["ex5"] is not None:
            b["e5"].append(row["ex5"])
        if row["ex20"] is not None:
            b["e20"].append(row["ex20"])
    for b in by.values():
        e5, e20 = b.pop("e5"), b.pop("e20")
        b.update(n5=len(e5), n20=len(e20), ex5=round(sum(e5) / len(e5), 2) if e5 else None,
                 ex20=round(sum(e20) / len(e20), 2) if e20 else None)
        out["models"].append(b)
    out["series"] = out["series"][-80:]
    return out
