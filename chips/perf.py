"""名單公布後的報酬計算（網站「之前的名單」與「實盤成績」共用）。

做法：名單公布後隔天開盤買進，持有到第 k 個交易日收盤；跟同一天、同市場所有合格股票用一樣方式買的等權平均比較。
"""
from .model import BENCH, Q_CLOSE, Q_DIFF, Q_EXR, Q_MKT, Q_OPEN, Q_VOL


def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def day_ret(q):
    """一天的報酬。一般用漲跌價差（對參考價，已扣除權息）；證交所除權息日的漲跌欄是 0，改用當天開盤到收盤。"""
    if not q or q[Q_CLOSE] is None:
        return None
    close, diff, opn = q[Q_CLOSE], q[Q_DIFF], q[Q_OPEN]
    if q[Q_EXR]:
        return close / opn - 1 if opn else None
    if diff is None or close == diff:
        return None
    return diff / (close - diff)


def hold(code, after, exf, k):
    """名單公布隔天開盤買進、持有到第 k 個交易日收盤的報酬（%）。隔天沒有開盤價（停牌等）回傳 None。"""
    q1 = exf(after[0])["q"].get(code)
    if not q1 or not q1[Q_OPEN] or q1[Q_CLOSE] is None:
        return None
    v = q1[Q_CLOSE] / q1[Q_OPEN]
    for d in after[1:k]:
        r = day_ret(exf(d)["q"].get(code))
        if r is not None:
            v *= 1 + r
    return round((v - 1) * 100, 2)


def universe(d, stored, exf, cfg):
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
