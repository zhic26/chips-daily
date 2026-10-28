"""下載一個交易日的盤後資料，整理成 data/daily/YYYY-MM-DD.json。

完整版（最近幾個交易日，用來計分）：行情、三大法人、融資融券、當沖、指數、法人金額。
精簡版（更早的日子，用來算季線、量能、融資趨勢）：只有行情與大盤統計，標記 light。
尚未公布的資料（例如晚上 9 點半前的融資融券）會記在 pending，下次執行再補抓。
"""
from . import sources as S
from .checks import check_day
from .net import FetchError

SOURCES = ["twse_inst", "twse_quotes", "tpex_inst", "tpex_quotes", "tpex_index", "twse_flows",
           "twse_margin", "tpex_margin", "twse_dt", "tpex_dt"]


def _i(v):
    if v is None:
        return None
    v = float(v)
    return int(v) if v.is_integer() else round(v, 4)


def _quote_row(v, market):
    return [v["name"], market, _i(v["close"]), _i(v["diff"]), _i(v["open"]), _i(v["high"]), _i(v["low"]),
            _i(v["vol"]), _i(v["amt"]), 1 if v.get("exRight") else 0]


def _inst_row(v):
    return [_i(v["foreign"]), _i(v["trust"]), _i(v["dealer"]), _i(v["total"])]


def _keep_etf(ex, etf, market):
    """ETF 收盤價（網頁「我的持股」用，不計分、不做資料檢查）：{代號: [名稱, 市場, 收盤, 漲跌]}。精簡版的日子不存。"""
    if ex.get("light"):
        return
    ex.setdefault("etf", {}).update({c: [v["name"], market, _i(v["close"]), _i(v["diff"])]
                                     for c, v in etf.items() if v["close"] is not None})


def fill_etf(d, ex):
    """更早存下、還沒有 ETF 收盤價的那天補抓一次行情（只取 ETF）。回傳是否有補。"""
    if "etf" in ex or ex.get("light") or "twse_quotes" in (ex.get("pending") or []):
        return False
    tw, tp = {}, {}
    S.twse_quotes(d, etf=tw)
    S.tpex_quotes(d, etf=tp)
    ex["etf"] = {}
    _keep_etf(ex, tw, "上市")
    _keep_etf(ex, tp, "上櫃")
    return True


def blank(d, light=False):
    ex = {"date": d.isoformat(), "fetchedAt": None, "pending": [] if light else list(SOURCES),
          "q": {}, "inst": {}, "margin": {}, "dt": {}, "shares": {}, "indices": {}, "market": {}}
    if light:
        ex["light"] = True
    return ex


def _run(src, d, ex, companies):
    ex.setdefault("market", {})
    if src in ("twse_inst", "tpex_inst"):
        r = (S.twse_inst if src == "twse_inst" else S.tpex_inst)(d)
        if not r:
            return False
        ex["inst"].update({c: _inst_row(v) for c, v in r.items()})
    elif src == "twse_quotes":
        etf = {}
        stocks, idx, stats = S.twse_quotes(d, etf=etf)
        if not stocks:
            return False
        _keep_etf(ex, etf, "上市")
        for c, v in stocks.items():
            ex["q"][c] = _quote_row(v, "上市")
            sh = (companies.get(c) or {}).get("shares")
            if sh and not ex.get("light"):
                ex["shares"][c] = _i(sh)
        ex["indices"].update(idx or {})
        if stats and stats.get("value"):
            ex["market"]["value"] = _i(stats["value"])
    elif src == "tpex_quotes":
        etf = {}
        stocks = S.tpex_quotes(d, etf=etf)
        if not stocks:
            return False
        _keep_etf(ex, etf, "上櫃")
        for c, v in stocks.items():
            ex["q"][c] = _quote_row(v, "上櫃")
            if v.get("shares") and not ex.get("light"):
                ex["shares"][c] = _i(v["shares"])
    elif src == "tpex_index":
        r = S.tpex_index(d)
        if not r:
            return False
        ex["indices"]["櫃買指數"] = r
    elif src == "twse_flows":
        r = S.twse_flows(d)
        if not r:
            return False
        ex["flows"] = {k: _i(v) for k, v in r.items()}
    elif src in ("twse_margin", "tpex_margin"):
        if src == "twse_margin":
            r, summary = S.twse_margin(d)
            if summary:
                ex["market"]["marginAmt"] = _i(summary["amt"])
                ex["market"]["marginAmtPrev"] = _i(summary["amtPrev"])
        else:
            r = S.tpex_margin(d)
        if not r:
            return False
        if not ex.get("light"):
            ex["margin"].update({c: [_i(v["mBal"]), _i(v["mChg"]), _i(v["sBal"]), _i(v["sChg"])] for c, v in r.items()})
    elif src in ("twse_dt", "tpex_dt"):
        r = (S.twse_daytrade if src == "twse_dt" else S.tpex_daytrade)(d)
        if not r:
            return False
        ex["dt"].update({c: [_i(v["dtVol"]), 1 if v["noShortFirst"] else 0] for c, v in r.items()})
    return True


def _stamp(ex):
    ex["fetchedAt"] = S.taipei_now().isoformat(timespec="minutes")


def fetch_day(d, companies, existing=None):
    """完整版。新的一天：證交所沒有法人資料就回傳 None（休市或尚未公布）。已有的一天：只補抓 pending 的來源。"""
    ex = existing or blank(d)
    fresh = existing is None
    changed = False
    for src in [s for s in SOURCES if s in ex["pending"]]:
        try:
            ok = _run(src, d, ex, companies)
        except FetchError as e:
            if fresh and src in ("twse_inst", "twse_quotes"):
                raise  # 連線問題，不是休市：讓這次執行失敗，下次排程再試
            print(f"  {src} 下載失敗，下次再補：{e}")
            ok = False
        if fresh and src == "twse_inst" and not ok:
            return None
        if ok:
            ex["pending"].remove(src)
            changed = True
    if fresh and "twse_quotes" in ex["pending"]:
        return None  # 法人有、行情沒有：資料還沒公布完整，先不存
    if changed or fresh:
        _stamp(ex)
        check_day(ex)  # 欄位錯位、筆數太少就丟出 DataError，這天不存
    return ex


def fetch_light(d, companies, with_flows):
    """精簡版：證交所沒有行情就回傳 None（休市）。with_flows：順便抓法人金額與融資總額（畫近 20 日趨勢用）。"""
    ex = blank(d, light=True)
    srcs = ["twse_quotes", "tpex_quotes"] + (["twse_flows", "twse_margin"] if with_flows else [])
    for src in srcs:
        try:
            ok = _run(src, d, ex, companies)
        except FetchError as e:
            if src == "twse_quotes":
                raise
            print(f"  {src} 下載失敗：{e}")
            ok = False
        if src == "twse_quotes" and not ok:
            return None
        if not ok:
            ex["pending"].append(src)
    _stamp(ex)
    check_day(ex)
    return ex


def backfill_market(ex, d, companies, with_flows):
    """舊檔缺少大盤統計（新功能上線前抓的）就補抓。回傳有沒有更新。"""
    m = ex.setdefault("market", {})
    todo = []
    if "value" not in m:
        todo.append("twse_quotes")
    if with_flows and "flows" not in ex and "twse_flows" not in ex.get("pending", []):
        todo.append("twse_flows")
    if with_flows and "marginAmt" not in m and "twse_margin" not in ex.get("pending", []):
        todo.append("twse_margin")
    changed = False
    for src in todo:
        try:
            changed |= _run(src, d, ex, companies)
        except FetchError as e:
            print(f"  {d} 補 {src} 失敗：{e}")
    return changed
