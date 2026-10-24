"""下載一個交易日的盤後資料，整理成 data/daily/YYYY-MM-DD.json。

尚未公布的資料（例如晚上 9 點半前的融資融券）會記在 pending，下次執行再補抓。
"""
from . import sources as S
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


def _run(src, d, ex, companies):
    if src in ("twse_inst", "tpex_inst"):
        r = (S.twse_inst if src == "twse_inst" else S.tpex_inst)(d)
        if not r:
            return False
        ex["inst"].update({c: _inst_row(v) for c, v in r.items()})
    elif src == "twse_quotes":
        stocks, idx = S.twse_quotes(d)
        if not stocks:
            return False
        for c, v in stocks.items():
            ex["q"][c] = _quote_row(v, "上市")
            sh = (companies.get(c) or {}).get("shares")
            if sh:
                ex["shares"][c] = _i(sh)
        ex["indices"].update(idx or {})
    elif src == "tpex_quotes":
        stocks = S.tpex_quotes(d)
        if not stocks:
            return False
        for c, v in stocks.items():
            ex["q"][c] = _quote_row(v, "上櫃")
            if v.get("shares"):
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
        r = (S.twse_margin if src == "twse_margin" else S.tpex_margin)(d)
        if not r:
            return False
        ex["margin"].update({c: [_i(v["mBal"]), _i(v["mChg"]), _i(v["sBal"]), _i(v["sChg"])] for c, v in r.items()})
    elif src in ("twse_dt", "tpex_dt"):
        r = (S.twse_daytrade if src == "twse_dt" else S.tpex_daytrade)(d)
        if not r:
            return False
        ex["dt"].update({c: [_i(v["dtVol"]), 1 if v["noShortFirst"] else 0] for c, v in r.items()})
    return True


def fetch_day(d, companies, existing=None):
    """新的一天：證交所沒有法人資料就回傳 None（休市或尚未公布）。已有的一天：只補抓 pending 的來源。"""
    ex = existing or {"date": d.isoformat(), "fetchedAt": None, "pending": list(SOURCES),
                      "q": {}, "inst": {}, "margin": {}, "dt": {}, "shares": {}, "indices": {}}
    fresh = existing is None
    changed = False
    for src in [s for s in SOURCES if s in ex["pending"]]:
        try:
            ok = _run(src, d, ex, companies)
        except FetchError as e:
            if fresh and src == "twse_inst":
                raise
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
        ex["fetchedAt"] = S.taipei_now().isoformat(timespec="minutes")
    return ex
