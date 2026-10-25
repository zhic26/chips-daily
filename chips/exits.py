"""參考進出場（依回測選出、以平均報酬最高為目標）：
名單公布隔天開盤買進；之後每天收盤後，只要分數掉到同市場第 rank 名以後，隔天開盤賣出；最多抱 max_days 個交易日（最後一天收盤賣）。

回測（2024/10～2026/7、17,480 筆）：平均抱 11 天，換算每 20 個交易日淨賺約 3.7%（固定抱 20 天約 2.6%），
勝率 43%（固定抱 20 天約 50%），最差 5% 的交易約 −13%（固定抱 20 天約 −20%）。
"""
from . import store
from .model import Q_OPEN
from .perf import hold, hold_open


def _ranker():
    cache = {}

    def rank_of(d, code, market):
        """d 收盤後的名次（1 起算）；不在前 RANK_KEEP 名回傳 999；那天沒有排名資料回傳 None（不判斷）。"""
        if d not in cache:
            doc = store.load_picks(d)
            cache[d] = (doc or {}).get("ranking")
        rk = cache[d]
        if not rk or market not in rk:
            return None
        lst = rk[market]
        return lst.index(code) + 1 if code in lst else 999
    return rank_of


def evaluate(cfg, dates, stored, exf):
    """dates：要追蹤的名單日期；stored：已存的交易日（舊到新）。回傳 {(日期, 代號): 狀態}。
    狀態：state＝holding（持有中）／sell（今天觸發，明天開盤賣）／sold（已賣出）／noentry（隔天沒有開盤價）。"""
    rule = cfg.get("exit") or {}
    lim, maxd = rule.get("rank", 80), rule.get("max_days", 60)
    rank_of = _ranker()
    out = {}
    for d in dates:
        doc = store.load_picks(d)
        after = [x for x in stored if x > d]
        if not doc or not after:
            continue
        for p in doc["picks"]:
            code, mk = p["code"], p["market"]
            key = (d.isoformat(), code)
            q1 = exf(after[0])["q"].get(code)
            if not q1 or not q1[Q_OPEN]:
                out[key] = {"state": "noentry"}
                continue
            st = None
            for k, t in enumerate(after):
                if k + 1 >= maxd:  # 抱滿 max_days 個交易日：當天收盤賣
                    st = {"state": "sold", "exit": t.isoformat(), "why": "max", "days": k + 1, "ret": hold(code, after, exf, k + 1)}
                    break
                r = rank_of(t, code, mk)
                if r is not None and r > lim:
                    if k + 1 < len(after):
                        st = {"state": "sold", "exit": after[k + 1].isoformat(), "why": "rank", "days": k + 2,
                              "ret": hold_open(code, after, exf, k + 1)}
                    else:
                        st = {"state": "sell", "rank": r, "days": k + 1, "ret": hold(code, after, exf, len(after))}
                    break
            if st is None:
                st = {"state": "holding", "rank": rank_of(after[-1], code, mk), "days": len(after),
                      "ret": hold(code, after, exf, len(after))}
            out[key] = st
    return out
