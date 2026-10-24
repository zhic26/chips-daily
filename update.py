#!/usr/bin/env python3
"""每日更新：下載盤後資料 → 計算籌碼分數 → 產生網頁 docs/index.html。

用法：
  python update.py               最近一個已有盤後資料的交易日
  python update.py 2026-10-23    指定日期（以這天為準往回找交易日）

只用 Python 標準函式庫，不需要安裝任何套件。
"""
import datetime as dt
import json
import sys

from chips import model, site, store
from chips import sources as S
from chips.bigholders import BigProvider
from chips.daily import fetch_day
from chips.net import FetchError

DEFAULTS = {
    "site": {"title": "籌碼日報", "tagline": "每個交易日盤後，用三大法人、千張大戶與融資變化篩出上市、上櫃各 20 檔。"},
    "top_n": 20,
    "lookback_days": 5,
    "min_avg_lots": 1000,
    "min_price": 10,
    "max_big_pct": 99,
    "daytrade_min_lots": 2000,
    "tdcc_candidates": 40,
    "tdcc_query_budget_seconds": 600,
    "backfill_days": 5,
    "history_days": 20,
    "keep_daily_days": 30,
    "weights": {"inst_today": 25, "inst_5d": 25, "consistency": 10, "big_holders": 25, "margin": 15},
}
STREAK_DAYS = 10


def load_cfg():
    cfg = json.loads(json.dumps(DEFAULTS))
    user = store.load_config()
    for k, v in user.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    if round(sum(cfg["weights"].values())) != 100:
        sys.exit(f"config.json 的 weights 加起來要等於 100（現在是 {sum(cfg['weights'].values())}）")
    return cfg


def companies():
    """上市櫃公司基本資料（產業別、上市股發行股數），一週更新一次。"""
    old = store.load_meta("companies") or {}
    age = store.meta_age_days("companies")
    if old and age is not None and age < 7:
        return old.get("data", {})
    data = dict(old.get("data", {}))
    try:
        for code, v in S.tpex_companies().items():
            data[code] = dict(data.get(code, {}), **v)
        for code, v in S.twse_companies().items():
            data[code] = dict(data.get(code, {}), **v)
        store.save_meta("companies", {"_saved": dt.date.today().isoformat(), "data": data})
        print(f"公司基本資料：{len(data)} 家")
    except Exception as e:
        print("公司基本資料下載失敗，沿用舊資料：", e)
    return data


def collect_days(target, need, today, comp):
    """從 target 往回找 need 個交易日，缺的就下載。回傳 (新到舊的日期, {日期: 資料})。"""
    nontrading = set((store.load_meta("nontrading") or {}).get("dates", []))
    days, exs = [], {}
    d = target
    while len(days) < need and (target - d).days < 60:
        if d.weekday() >= 5 or d.isoformat() in nontrading:
            d -= dt.timedelta(days=1)
            continue
        ex = store.load_daily(d)
        if ex is None:
            print(f"下載 {d} 盤後資料…", flush=True)
            ex = fetch_day(d, comp)
            if ex is None:
                print(f"  {d} 沒有資料（休市或尚未公布）")
                if (today - d).days >= 3:
                    nontrading.add(d.isoformat())
                d -= dt.timedelta(days=1)
                continue
            store.save_daily(d, ex)
        elif ex["pending"] and (today - d).days <= 3:
            before = list(ex["pending"])
            print(f"補抓 {d} 尚未公布的資料：{', '.join(before)}", flush=True)
            ex = fetch_day(d, comp, existing=ex)
            if ex["pending"] != before:
                store.save_daily(d, ex)
        if ex["pending"]:
            print(f"  {d} 仍缺：{', '.join(ex['pending'])}")
        days.append(d)
        exs[d] = ex
        d -= dt.timedelta(days=1)
    store.save_meta("nontrading", {"dates": sorted(nontrading)})
    return days, exs


def same(a, b):
    strip = lambda x: {k: v for k, v in (x or {}).items() if k != "generatedAt"}
    return json.dumps(strip(a), sort_keys=True) == json.dumps(strip(b), sort_keys=True)


def main():
    cfg = load_cfg()
    now = S.taipei_now()
    today = now.date()
    target = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].strip() else today
    comp = companies()

    have_picks = store.picks_dates()
    backfill = cfg["backfill_days"] if len(have_picks) < cfg["backfill_days"] else 1
    need = max(cfg["lookback_days"] + backfill - 1, cfg["lookback_days"])
    try:
        days, exs = collect_days(target, need, today, comp)
    except FetchError as e:
        sys.exit(f"證交所資料下載失敗：{e}")
    if len(days) < cfg["lookback_days"]:
        sys.exit("找不到足夠的交易日資料")
    print("交易日：", " ".join(f"{d:%m/%d}" for d in days))

    # 已存下、更早的日子也載入，用來算連買天數
    for d in store.daily_dates():
        if d < days[-1] and len(days) < max(need, STREAK_DAYS):
            days.append(d)
            exs[d] = store.load_daily(d)

    try:
        week, big = S.tdcc_latest()
        if week and store.save_tdcc(week, big):
            print(f"集保：新增 {week} 週資料（{len(big)} 檔）")
    except Exception as e:
        print("集保開放資料下載失敗：", e)

    provider = BigProvider(cfg["tdcc_query_budget_seconds"])
    for i in range(min(backfill, len(days) - cfg["lookback_days"] + 1)):
        d = days[i]
        old = store.load_picks(d)
        if i > 0 and old:
            continue
        doc = model.compute_day(days[i:i + STREAK_DAYS], exs, cfg, comp, provider)
        doc["generatedAt"] = now.isoformat(timespec="minutes")
        if same(doc, old):
            print(f"{d} 選股結果沒有變化")
            continue
        store.save_picks(d, doc)
        t = doc["tdcc"]
        print(f"{d} 選股：上市 {sum(p['market'] == '上市' for p in doc['picks'])} 檔、上櫃 "
              f"{sum(p['market'] == '上櫃' for p in doc['picks'])} 檔｜集保 {t['week']} vs {t['prevWeek']}（{t['mode']}）"
              f"｜待補：{', '.join(doc['pending']) or '無'}")
        for p in doc["picks"][:3]:
            print(f"   {p['market']} {p['rank']:>2}. {p['code']} {p['name']} {p['score']} {p['tags']}")
    provider.flush()
    if provider.queried:
        print(f"集保逐檔查詢 {provider.queried} 次")

    site.build(cfg, now)
    store.prune_daily(cfg["keep_daily_days"])
    print("完成")


if __name__ == "__main__":
    main()
