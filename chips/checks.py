"""資料檢查：官方網站改版、欄位錯位或資料不完整時，讓這次執行失敗，而不是悄悄發布錯的名單。

檢查的是「存進 data/daily 之前的一天資料」和「存進 data/picks 之前的名單」。
門檻抓得很寬（平常的六、七成），正常的日子不會誤判；真的改版時通常整欄都會錯，一定會超過門檻。
"""
import math

# 每日資料一列的欄位位置（與 daily._quote_row 相同；model.py 另有一份給計分用）
_NAME, _MKT, _CLOSE, _DIFF, _OPEN, _HIGH, _LOW, _VOL, _AMT, _EXR = range(10)

# 平常約：上市 1,050～1,100 檔、上櫃 800～900 檔
MIN_QUOTES = {"上市": 700, "上櫃": 500}
MIN_INST = {"上市": 600, "上櫃": 400}
MIN_MARGIN = {"上市": 600, "上櫃": 400}
MIN_DT = {"上市": 500, "上櫃": 300}
SRC = {"上市": "twse", "上櫃": "tpex"}


class DataError(Exception):
    """資料下載成功，但內容看起來不對（欄位改了、筆數太少、數字不合理）。"""


def need(cond, msg):
    if not cond:
        raise DataError(msg)


def share(items, pred):
    """items 中符合 pred 的比例；沒有資料時回傳 1（不判定為錯）。"""
    items = list(items)
    return sum(1 for x in items if pred(x)) / len(items) if items else 1.0


def _vwap_ok(r):
    return r[_LOW] * 0.95 <= r[_AMT] / r[_VOL] <= r[_HIGH] * 1.05


def _limit_ok(r):
    base = r[_CLOSE] - r[_DIFF]
    return base > 0 and abs(r[_DIFF]) / base <= 0.105


def check_day(ex):
    """一天的盤後資料（data/daily 的格式）。還在 pending 的來源不檢查。"""
    d, q, pend = ex["date"], ex["q"], set(ex.get("pending") or [])
    by = {mk: {c: r for c, r in q.items() if r[_MKT] == mk} for mk in MIN_QUOTES}
    for mk, rows in by.items():
        src = SRC[mk]
        if src + "_quotes" not in pend:
            need(len(rows) >= MIN_QUOTES[mk], f"{d} {mk}行情只有 {len(rows)} 檔，平常約 1,000 檔，可能是網站改版")
            vals = list(rows.values())
            need(share(vals, lambda r: r[_CLOSE] is not None and r[_CLOSE] > 0) >= 0.8, f"{d} {mk}行情大多沒有收盤價")
            full = [r for r in vals if None not in (r[_CLOSE], r[_HIGH], r[_LOW])]
            need(share(full, lambda r: r[_LOW] <= r[_CLOSE] <= r[_HIGH]) >= 0.99, f"{d} {mk}行情的收盤價不在最高、最低價之間，欄位可能錯位")
            moved = [r for r in vals if r[_CLOSE] and r[_DIFF] is not None and not r[_EXR]]
            need(share(moved, _limit_ok) >= 0.98, f"{d} {mk}行情的漲跌幅大多超過 10%，漲跌欄位可能錯位")
            traded = [r for r in vals if r[_VOL] and r[_AMT] and r[_HIGH] and r[_LOW]]
            need(share(traded, _vwap_ok) >= 0.95, f"{d} {mk}行情的成交金額 ÷ 成交股數不像股價，單位或欄位可能改了")
        if ex.get("light"):
            continue
        if src + "_inst" not in pend:
            inst = [ex["inst"][c] for c in rows if c in ex["inst"]]
            need(len(inst) >= MIN_INST[mk], f"{d} {mk}三大法人只有 {len(inst)} 檔")
            need(share(inst, lambda v: abs(v[0] + v[1] + v[2] - v[3]) <= max(abs(v[3]) * 0.01, 1000)) >= 0.95,
                 f"{d} {mk}三大法人：外資＋投信＋自營商不等於合計，欄位可能錯位")
            need(share(inst, lambda v: v[3] != 0) >= 0.3, f"{d} {mk}三大法人買賣超幾乎都是 0")
            both = [(ex["inst"][c][3], r[_VOL]) for c, r in rows.items() if c in ex["inst"] and r[_VOL]]
            need(share(both, lambda t: abs(t[0]) <= t[1]) >= 0.99, f"{d} {mk}三大法人買賣超大於成交量，單位可能改了")
        if src + "_margin" not in pend:
            mg = [ex["margin"][c] for c in rows if c in ex["margin"]]
            need(len(mg) >= MIN_MARGIN[mk], f"{d} {mk}融資融券只有 {len(mg)} 檔")
            need(share(mg, lambda v: (v[0] or 0) >= 0 and (v[2] or 0) >= 0) >= 0.999, f"{d} {mk}融資或融券餘額出現負數，欄位可能錯位")
            need(share(mg, lambda v: (v[0] or 0) - (v[1] or 0) >= 0) >= 0.99, f"{d} {mk}融資餘額減掉今天增減後變成負數，欄位可能錯位")
        if src + "_dt" not in pend:
            dt = [(ex["dt"][c][0], r[_VOL]) for c, r in rows.items() if c in ex["dt"]]
            need(len(dt) >= MIN_DT[mk], f"{d} {mk}當沖資料只有 {len(dt)} 檔")
            need(share(dt, lambda t: t[1] is None or (t[0] or 0) <= t[1] * 1.01) >= 0.99, f"{d} {mk}當沖量大於成交量，單位可能改了")
    if "twse_quotes" not in pend:
        tw = (ex.get("indices") or {}).get("加權指數") or {}
        need((tw.get("close") or 0) > 1000, f"{d} 找不到加權指數")
    return True


def _finite(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def check_picks(doc, cfg):
    """存檔前的名單：每個市場名次從 1 連續排下去、分數合理且由高到低、沒有重複、權重加總 100。"""
    d = doc["date"]
    need(abs(sum(cfg["weights"].values()) - 100) < 1e-6, "權重加總不是 100")
    picks = doc["picks"]
    need(len({p["code"] for p in picks}) == len(picks), f"{d} 名單有重複的股票")
    for mk in MIN_QUOTES:
        grp = [p for p in picks if p["market"] == mk]
        if doc["universe"].get(mk, 0) >= 100:
            need(len(grp) >= min(cfg["top_n"], 5), f"{d} {mk}名單只有 {len(grp)} 檔")
        need(len(grp) <= cfg["top_n"], f"{d} {mk}名單超過 {cfg['top_n']} 檔")
        need([p["rank"] for p in grp] == list(range(1, len(grp) + 1)), f"{d} {mk}名次不是從 1 連續排下去")
        scores = [p["score"] for p in grp]
        need(all(_finite(s) and 0 <= s <= 100 for s in scores), f"{d} {mk}分數超出 0～100")
        need(all(a >= b for a, b in zip(scores, scores[1:])), f"{d} {mk}分數沒有由高到低排")
        need(all(p.get("name") and _finite(p.get("close")) and p["close"] > 0 for p in grp), f"{d} {mk}名單缺少股名或收盤價")
        need(all(_finite(v) for p in grp for v in p["parts"].values()), f"{d} {mk}分項分數有空值")
        rk = (doc.get("ranking") or {}).get(mk)
        if rk is not None:
            need(len(rk) == len(set(rk)), f"{d} {mk}全市場排名有重複的股票")
            need(len(rk) >= min(len(grp), 1), f"{d} {mk}全市場排名是空的")
    return True
