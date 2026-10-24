"""千張大戶持股與週變化。

平常用集保開放資料每週存下的快照（data/tdcc/）。剛開始還沒有前一週的快照時，
改用集保網站的逐檔查詢補齊（只查候選股，結果存在 data/tdcc_query/，有時間上限）。
"""
import datetime as dt
import time

from . import store
from .net import FetchError
from .sources import TdccQuery


def _d(week):
    return dt.date(int(week[:4]), int(week[4:6]), int(week[6:]))


class BigProvider:
    def __init__(self, budget_seconds=480):
        self.snap_weeks = store.tdcc_weeks()
        self._snaps = {}
        self._query = None
        self._query_dead = False
        self._form_weeks = None
        self._cache = {}
        self._dirty = set()
        self.deadline = time.monotonic() + budget_seconds
        self.queried = 0
        self.failures = 0

    # ---- 週別 ----
    def _snapshot(self, week):
        if week not in self._snaps:
            self._snaps[week] = store.load_tdcc(week) if week in self.snap_weeks else None
        return self._snaps[week]

    def form_weeks(self):
        if self._form_weeks is None:
            self._form_weeks = []
            if not self._query_dead:
                try:
                    self._query = self._query or TdccQuery()
                    self._form_weeks = sorted(set(self._query.available_weeks()))
                except Exception as e:  # 集保網站暫時連不上：當作沒有舊週資料
                    print("  集保查詢頁連線失敗：", e)
                    self._query_dead = True
        return self._form_weeks

    def week_pair(self, day):
        """回傳 (本週, 前一週)：本週 = 資料日期不晚於 day 的最新一週。"""
        target = day.strftime("%Y%m%d")
        snaps = [w for w in self.snap_weeks if w <= target]
        cur = snaps[-1] if snaps else None
        if cur is None:
            older = [w for w in self.form_weeks() if w <= target]
            cur = older[-1] if older else None
        if cur is None:
            return None, None
        prev_snaps = [w for w in self.snap_weeks if w < cur]
        prev = prev_snaps[-1] if prev_snaps else None
        # 兩份快照相隔超過 9 天代表中間漏了一週，改用查詢頁的週別清單找真正的前一週
        if prev is None or (_d(cur) - _d(prev)).days > 9:
            older = [w for w in self.form_weeks() if w < cur]
            if older and (prev is None or older[-1] > prev):
                prev = older[-1]
        return cur, prev

    # ---- 逐檔查詢 ----
    def query(self, week, code):
        cache = self._cache.setdefault(week, store.load_tdcc_query(week))
        if code in cache:
            return cache[code]
        if self._query_dead or time.monotonic() > self.deadline:
            return None
        try:
            self._query = self._query or TdccQuery()
            if not self._query.weeks:
                self._query.available_weeks()
            v = self._query.big_pct(code, week)
            self.failures = 0
        except (FetchError, Exception) as e:
            self.failures += 1
            print(f"  集保查詢失敗 {code} {week}：{e}")
            if self.failures >= 5:
                print("  集保查詢連續失敗，本次停止查詢")
                self._query_dead = True
            return None
        self.queried += 1
        cache[code] = v
        self._dirty.add(week)
        if self.queried % 25 == 0:
            self.flush()
        return v

    def flush(self):
        for w in list(self._dirty):
            store.save_tdcc_query(w, self._cache[w])
        self._dirty.clear()

    def lookup_for(self, day):
        return Lookup(self, *self.week_pair(day))


class Lookup:
    def __init__(self, provider, cur, prev):
        self.p, self.cur, self.prev = provider, cur, prev
        self.cur_snap = provider._snapshot(cur) if cur else None
        self.prev_snap = provider._snapshot(prev) if prev else None
        self.full = self.cur_snap is not None and self.prev_snap is not None
        self.missing = 0

    def _get(self, week, snap, code):
        if week is None:
            return None
        if snap is not None:
            return snap.get(code)
        return self.p.query(week, code)

    def __call__(self, codes):
        out = {}
        for c in codes:
            pct = self._get(self.cur, self.cur_snap, c)
            prev = self._get(self.prev, self.prev_snap, c)
            chg = round(pct - prev, 2) if pct is not None and prev is not None else None
            if chg is None:
                self.missing += 1
            out[c] = (pct, chg)
        return out

    def describe(self):
        fmt = lambda w: f"{w[:4]}-{w[4:6]}-{w[6:]}" if w else None
        mode = "snapshot" if self.full else ("query" if self.cur else "none")
        return {"week": fmt(self.cur), "prevWeek": fmt(self.prev), "mode": mode, "missing": self.missing}
