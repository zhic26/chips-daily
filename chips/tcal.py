"""交易日曆：用證交所公布的開休市日期（每年一份）推算「下一個交易日」和「第 N 個交易日」。
還沒公布的年份只排除週末，網頁會標「約」；颱風假之類的臨時休市事先不知道。"""
import datetime as dt

from . import store
from .checks import DataError
from .net import FetchError, get_json

URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date={y}0101&response=json"


def parse(j):
    """證交所開休市表 → 休市日（ISO 日期）。名稱有「開始交易」「最後交易」的是有交易的日子。"""
    if not isinstance(j, dict) or "data" not in j:
        raise DataError("證交所開休市日期回應格式變了")
    out = []
    for r in j.get("data") or []:
        name = str(r[1]) if len(r) > 1 else ""
        if "開始交易" in name or "最後交易" in name:
            continue
        try:
            out.append(dt.date.fromisoformat(str(r[0]).strip()).isoformat())
        except ValueError as e:
            raise DataError(f"證交所開休市日期看不懂：{r[0]}") from e
    return out


def refresh(years, today, problems):
    """抓需要的年份存到 data/meta/holidays.json（每 30 天重抓一次；還沒公布的年份下次再試）。"""
    cache = store.load_meta("holidays", {}) or {}
    have = cache.get("years") or {}
    age = store.meta_age_days("holidays")
    stale = age is None or age >= 30
    changed = False
    for y in years:
        if str(y) in have and not stale:
            continue
        try:
            j = get_json(URL.format(y=y))
            if j and j.get("data"):
                have[str(y)] = parse(j)
                changed = True
        except FetchError as e:
            print(f"  證交所 {y} 年休市日期下載失敗：{e}")
        except DataError as e:
            problems.append(str(e))
    if changed:
        store.save_meta("holidays", {"_saved": today.isoformat(), "years": have})
    return have


def nth_trading_day(d, n, years, extra=()):
    """d 之後的第 n 個交易日。回傳 (日期, 是否推估)：遇到還沒公布休市表的年份就算推估。"""
    cur, k, approx, extra = d, 0, False, set(extra)
    while k < n:
        cur += dt.timedelta(days=1)
        if cur.weekday() >= 5 or cur.isoformat() in extra:
            continue
        closed = years.get(str(cur.year))
        if closed is None:
            approx = True
        elif cur.isoformat() in closed:
            continue
        k += 1
    return cur, approx
