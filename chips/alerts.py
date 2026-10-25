"""注意股、處置股：抓最近幾個交易日的注意股公告和近期的處置股，存在 data/meta/alerts.json。

只用來在名單上標示，不影響分數。抓不到時名單照常更新，只是少了這些標籤（網頁上會註明）。
"""
import datetime as dt

from . import sources as S
from . import store
from .checks import DataError
from .net import FetchError

KEEP_DAYS = 60     # 注意股公告保留幾天（算連續被列幾天用）
PUNISH_DAYS = 45   # 處置股往回查幾天的公布日期（處置期間通常 5～10 個營業日）
MARKETS = (("twse", "上市", S.twse_notice, S.twse_punish), ("tpex", "上櫃", S.tpex_notice, S.tpex_punish))


def _final(d, now):
    """注意股是收盤後公告的。晚上 8 點以後抓到的才存起來；更早抓到的這次照用，但下次會重抓。"""
    return now.date() > d or now.hour >= 20


def update(days, now):
    """days：要用到的交易日（新到舊）。回傳 (資料, 問題清單)。
    問題清單只放格式錯誤（網站改版），連線失敗只印出來，下次執行會再抓。"""
    al = store.load_meta("alerts", {}) or {}
    notice = al.setdefault("notice", {})
    punish = al.setdefault("punish", {})
    live = {}
    problems = []
    for mkt, label, f_notice, f_punish in MARKETS:
        saved = notice.setdefault(mkt, {})
        todo = [d for d in days if d.isoformat() not in saved]
        if todo:
            try:
                got = f_notice(min(todo), max(todo))
                live[mkt] = {d.isoformat(): got.get(d.isoformat(), {}) for d in todo}
                saved.update({d.isoformat(): got.get(d.isoformat(), {}) for d in todo if _final(d, now)})
            except FetchError as e:
                print(f"  {label}注意股下載失敗，下次再補：{e}")
            except DataError as e:
                problems.append(str(e))
        try:
            punish[mkt] = f_punish(now.date() - dt.timedelta(days=PUNISH_DAYS), now.date())
        except FetchError as e:
            print(f"  {label}處置股下載失敗，先用上次的資料：{e}")
        except DataError as e:
            problems.append(str(e))
    cut = (now.date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for mkt in notice:
        notice[mkt] = {k: v for k, v in notice[mkt].items() if k >= cut}
    al["_saved"] = now.date().isoformat()
    store.save_meta("alerts", al)
    for mkt, extra in live.items():
        notice[mkt] = dict(notice[mkt], **extra)
    return al, problems


def for_day(al, d, days):
    """d 收盤後的狀態：({代號: {"notice": 連續被列幾個交易日, "why": 原因, "punish": {...}}}, 缺資料的市場)。
    處置股：已經公布、而且處置期間在 d 之後還沒結束（隔天開盤買進時多半還在處置中）。"""
    iso = d.isoformat()
    prev = [x.isoformat() for x in days if x <= d]  # 新到舊
    out, missing = {}, []
    for mkt, label, _, _ in MARKETS:
        nd = (al.get("notice") or {}).get(mkt) or {}
        if iso not in nd:
            missing.append(label)
            continue
        for code, why in nd[iso].items():
            n = 0
            for x in prev:
                if code not in nd.get(x, {}):
                    break
                n += 1
            out[code] = {"notice": n, "why": why}
    for mkt, _, _, _ in MARKETS:
        for p in (al.get("punish") or {}).get(mkt) or []:
            if p["ann"] <= iso < p["end"]:
                out.setdefault(p["code"], {})["punish"] = {k: p[k] for k in ("start", "end", "step", "mins", "prepay")}
    return out, missing
