#!/usr/bin/env python3
"""每日更新：下載盤後資料 → 計算籌碼分數與大盤體溫 → 產生網頁 docs/index.html。

用法：
  python update.py               最近一個已有盤後資料的交易日
  python update.py 2026-10-23    指定日期（以這天為準往回找交易日）

只用 Python 標準函式庫，不需要安裝任何套件。
"""
import datetime as dt
import json
import sys

from chips import alerts as A
from chips import model, site, store
from chips import sources as S
from chips.checks import DataError, check_picks
from chips.bigholders import BigProvider
from chips.daily import backfill_market, fetch_day, fetch_light
from chips.net import FetchError

STALE_WEEKDAYS = 8  # 超過這麼多個平日都沒抓到新資料，就當作出問題（農曆年連假最長約 7 個平日）

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
    "history_days": 30,  # 後續表現列出最近幾份名單（要滿 20 個交易日才有 20 日報酬）
    "market_history_days": 80,   # 算季線（60 日均線）和近 20 日趨勢需要的交易日數
    "keep_daily_days": 85,
    # 權重依 2024/10～2026/10 回測調整：連買天數最有用、買超張數幾乎沒有預測力，融資看近 5 日
    "weights": {"inst_today": 10, "inst_5d": 10, "consistency": 30, "big_holders": 15, "margin": 15, "revenue": 20},
    # 籌碼偏重：融資 5 日增幅、20 日漲幅超過門檻就標示；deduct=true 才會扣分（回測扣分沒有提高報酬）
    "crowding": {"margin_5d_pct": [10, 20], "margin_min_lots": 300, "runup_20d_pct": [30, 50], "points": [5, 10],
                 "max_penalty": 15, "deduct": False},
}
STREAK_DAYS = 10
RECENT_FLOW_DAYS = 21


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


def revenue_update(today):
    """月營收：每月 10 日前公布上個月的數字，11 日起才抓並使用（和回測的規則一樣）。回傳 {YYYY-MM: {代號: [營收, 去年同月]}}。"""
    have = set(store.revenue_months())
    y, m = today.year, today.month
    for back in range(1, 5):  # 最近 4 個已過公布期限的月份
        yy, mm = y, m - back
        while mm <= 0:
            yy, mm = yy - 1, mm + 12
        ym = f"{yy}-{mm:02d}"
        due = dt.date(yy + (mm == 12), mm % 12 + 1, 11)
        if ym in have or today < due:
            continue
        try:
            data = S.mops_revenue(yy, mm)
        except Exception as e:  # 公開資訊觀測站暫時連不上：下次再補
            print(f"月營收 {ym} 下載失敗：{e}")
            continue
        if len(data) > 1000:
            store.save_revenue(ym, {"ym": ym, "fetchedAt": today.isoformat(), "data": data})
            print(f"月營收：存入 {ym}（{len(data)} 家）")
    return {ym: (store.load_revenue(ym) or {}).get("data", {}) for ym in store.revenue_months()[-6:]}


class Calendar:
    """記住哪些平日沒有交易（颱風假、國定假日），避免每次重抓。"""

    def __init__(self, today):
        self.today = today
        self.dates = set((store.load_meta("nontrading") or {}).get("dates", []))
        self.dirty = False

    def closed(self, d):
        return d.weekday() >= 5 or d.isoformat() in self.dates

    def mark(self, d):
        if (self.today - d).days >= 3 and d.isoformat() not in self.dates:  # 太近的日子可能只是還沒公布
            self.dates.add(d.isoformat())
            self.dirty = True

    def save(self):
        if self.dirty:
            store.save_meta("nontrading", {"dates": sorted(self.dates)})


def collect_days(target, need, cal, comp):
    """從 target 往回找 need 個交易日的完整資料，缺的就下載。回傳 (新到舊的日期, {日期: 資料})。"""
    days, exs = [], {}
    d = target
    while len(days) < need and (target - d).days < 60:
        if cal.closed(d):
            d -= dt.timedelta(days=1)
            continue
        ex = store.load_daily(d)
        if ex is None or ex.get("light"):
            print(f"下載 {d} 盤後資料…", flush=True)
            ex = fetch_day(d, comp)
            if ex is None:
                print(f"  {d} 沒有資料（休市或尚未公布）")
                cal.mark(d)
                d -= dt.timedelta(days=1)
                continue
            store.save_daily(d, ex)
        elif ex["pending"] and (cal.today - d).days <= 3:
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
    return days, exs


def ensure_history(latest, need, cal, comp, exs):
    """確保 latest 往回有 need 個交易日的行情（季線、量能、融資趨勢用），舊日子只抓精簡版。"""
    have = []
    d = latest
    fetched = 0
    while len(have) < need and (latest - d).days < need * 2 + 40:
        if cal.closed(d):
            d -= dt.timedelta(days=1)
            continue
        with_flows = len(have) < RECENT_FLOW_DAYS
        ex = exs.get(d) or store.load_daily(d)
        if ex is None:
            if fetched == 0:
                print("補抓歷史行情（第一次會比較久）…", flush=True)
            ex = fetch_light(d, comp, with_flows)
            fetched += 1
            if ex is None:
                cal.mark(d)
                d -= dt.timedelta(days=1)
                continue
            store.save_daily(d, ex)
        elif backfill_market(ex, d, comp, with_flows):
            store.save_daily(d, ex)
        exs[d] = ex
        have.append(d)
        d -= dt.timedelta(days=1)
    if fetched:
        print(f"  補了 {fetched} 天歷史行情，共 {len(have)} 個交易日")
    return have


def same(a, b):
    strip = lambda x: {k: v for k, v in (x or {}).items() if k != "generatedAt"}
    return json.dumps(strip(a), sort_keys=True) == json.dumps(strip(b), sort_keys=True)


def main():
    cfg = load_cfg()
    now = S.taipei_now()
    today = now.date()
    target = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].strip() else today
    comp = companies()
    revenue = revenue_update(today)
    cal = Calendar(today)

    recent = store.picks_dates()[:cfg["backfill_days"]]
    outdated = [d for d in recent if (store.load_picks(d) or {}).get("model") != model.MODEL_VERSION]
    backfill = cfg["backfill_days"] if len(recent) < cfg["backfill_days"] or outdated else 1
    need = max(cfg["lookback_days"] + backfill - 1, cfg["lookback_days"])
    try:
        days, exs = collect_days(target, need, cal, comp)
        if len(days) < cfg["lookback_days"]:
            sys.exit("找不到足夠的交易日資料")
        gap = sum(1 for k in range(1, (target - days[0]).days + 1) if (days[0] + dt.timedelta(days=k)).weekday() < 5)
        if gap > STALE_WEEKDAYS:
            raise DataError(f"最新資料停在 {days[0]}，已經 {gap} 個平日沒有新資料（連假最多約 7 天），"
                            "可能是網站改版，讓每天都被當成休市")
        hist = ensure_history(days[0], cfg["market_history_days"] + backfill - 1, cal, comp, exs)
    except FetchError as e:
        cal.save()
        sys.exit(f"證交所資料下載失敗：{e}")
    except DataError as e:
        sys.exit(f"資料檢查沒通過，這次不更新名單（請檢查官方網站是否改版）：{e}")
    cal.save()
    print("交易日：", " ".join(f"{d:%m/%d}" for d in days))

    full = [d for d in hist if not exs[d].get("light")]  # 有完整資料的日子（算連買天數用）
    problems = []  # 不影響分數、但格式看起來不對的資料：名單照常更新，最後讓這次執行顯示失敗以便通知

    try:
        al, bad = A.update(full[:backfill + 5], now)
        problems += bad
    except Exception as e:  # 注意／處置股只是標籤，任何錯誤都不擋住名單
        al = None
        problems.append(f"注意／處置股：{e!r}")

    try:
        week, big, tdcc_full = S.tdcc_latest()
        if week and (len(big) < 1500 or not all(0 <= v <= 100 for v in big.values())):
            problems.append(f"集保開放資料只有 {len(big)} 檔或比例超出 0～100，這週先不存")
            week = None
        if week and tdcc_full and store.save_tdcc_full(week, tdcc_full):
            print(f"集保：存入 {week} 股東人數與級距（{len(tdcc_full)} 檔）")
        if week and store.save_tdcc(week, big):
            print(f"集保：新增 {week} 週資料（{len(big)} 檔）")
    except Exception as e:
        print("集保開放資料下載失敗：", e)

    provider = BigProvider(cfg["tdcc_query_budget_seconds"])
    history = model.History(hist, exs)
    for i in range(min(backfill, len(days) - cfg["lookback_days"] + 1)):
        d = days[i]
        old = store.load_picks(d)
        if i > 0 and old and old.get("model") == model.MODEL_VERSION:
            continue
        streak_days = [x for x in full if x <= d][:STREAK_DAYS]
        doc = model.compute_day(streak_days, exs, cfg, comp, provider, history, revenue,
                                alerts=A.for_day(al, d, full) if al else None)
        doc["generatedAt"] = now.isoformat(timespec="minutes")
        try:
            check_picks(doc, cfg)
        except DataError as e:
            sys.exit(f"名單檢查沒通過，這次不更新：{e}")
        if same(doc, old):
            print(f"{d} 結果沒有變化")
            continue
        store.save_picks(d, doc)
        t = doc["tdcc"]
        print(f"{d} 選股：上市 {sum(p['market'] == '上市' for p in doc['picks'])} 檔、上櫃 "
              f"{sum(p['market'] == '上櫃' for p in doc['picks'])} 檔｜集保 {t['week']} vs {t['prevWeek']}（{t['mode']}）"
              f"｜待補：{', '.join(doc['pending']) or '無'}")
        for p in doc["picks"][:3]:
            print(f"   {p['market']} {p['rank']:>2}. {p['code']} {p['name']} {p['score']} {p['tags']}")
        tm = doc.get("temp") or {}
        if tm:
            print("   大盤體溫：", "；".join(tm.get("read", [])))
    provider.flush()
    if provider.queried:
        print(f"集保逐檔查詢 {provider.queried} 次")

    site.build(cfg, now)
    store.prune_daily(cfg["keep_daily_days"])
    if problems:
        print("名單已更新，但有資料格式看起來不對（請檢查官方網站是否改版）：")
        for x in problems:
            print("  -", x)
        sys.exit(1)
    print("完成")


if __name__ == "__main__":
    main()
