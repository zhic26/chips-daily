"""國際盤勢：Yahoo 走勢圖的解析（去掉週末和還沒收盤的那根）、ADR 溢價、聯準會會議日程、事件時間換算、文字說明。"""
import datetime as dt
import json
import os
import tempfile
import unittest

from chips import macro as M
from chips import store
from chips.checks import DataError
from chips.net import FetchError
from tests.helpers import FIX

TPE = dt.timezone(dt.timedelta(hours=8))


def chart(name):
    with open(os.path.join(FIX, "macro", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


class Chart(unittest.TestCase):
    def test_after_close(self):
        s = M.parse_chart(chart("SOX"), dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE).timestamp())
        self.assertEqual(s[-1][0], "2026-10-23")
        self.assertGreater(len(s), 100)
        self.assertEqual(len({d for d, _ in s}), len(s))

    def test_session_in_progress(self):
        """美股還在交易（台北時間晚上）時，最後一根還沒收盤，要去掉。"""
        reg = chart("SOX")["chart"]["result"][0]["meta"]["currentTradingPeriod"]["regular"]
        s = M.parse_chart(chart("SOX"), reg["start"] + 3600)
        self.assertEqual(s[-1][0], "2026-10-22")

    def test_weekend_and_fx(self):
        s = M.parse_chart(chart("TWD_X"), dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE).timestamp())
        self.assertEqual(s[-1][0], "2026-10-23")  # 週日的零星報價不算
        self.assertTrue(all(dt.date.fromisoformat(d).weekday() < 5 for d, _ in s))
        self.assertTrue(all(25 < v < 40 for _, v in s))

    def test_futures_and_rates(self):
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE).timestamp()
        self.assertEqual(M.parse_chart(chart("CL_F"), now)[-1][0], "2026-10-23")
        self.assertTrue(all(0.1 < v < 20 for _, v in M.parse_chart(chart("TNX"), now)))

    def test_broken(self):
        with self.assertRaises(DataError):
            M.parse_chart({"chart": {"result": None}}, 0)

    def test_stats(self):
        s = [(f"2026-01-{i + 1:02d}", 100.0 + i) for i in range(60)]
        st = M.stats(s)
        self.assertEqual(st["last"], 159.0)
        self.assertAlmostEqual(st["chg1"], (159 / 158 - 1) * 100, places=2)
        self.assertAlmostEqual(st["chg20"], (159 / 139 - 1) * 100, places=2)
        self.assertEqual(st["d20"], 20.0)
        self.assertAlmostEqual(st["ma50"], (159 / (sum(range(110, 160)) / 50) - 1) * 100, places=2)
        self.assertEqual(len(st["spark"]), 60)


class Adr(unittest.TestCase):
    def test_premium(self):
        tsm = [("2026-10-21", 100.0), ("2026-10-22", 110.0)]
        twd = [("2026-10-20", 32.0)]
        tw = {"2026-10-21": 500.0, "2026-10-22": 500.0, "2026-10-23": 510.0}
        out = M.adr_premium(tsm, twd, tw)
        self.assertEqual([d for d, _ in out], ["2026-10-21", "2026-10-22"])  # 沒有 ADR 收盤的日子不算
        self.assertAlmostEqual(out[0][1], (100 / (500 * 5 / 32) - 1) * 100, places=2)


class Fomc(unittest.TestCase):
    def test_fixture(self):
        with open(os.path.join(FIX, "macro", "fomc.html"), encoding="utf-8") as f:
            m = M.parse_fomc(f.read())
        d = {x["date"]: x["sep"] for x in m}
        self.assertEqual(d.get("2026-10-28"), False)
        self.assertEqual(d.get("2026-12-09"), True)
        self.assertGreaterEqual(sum(1 for x in d if x.startswith("2026")), 8)

    def test_cross_month_and_notation(self):
        html = ('<h4>2027 FOMC Meetings</h4>'
                '<div class="fomc-meeting__month"><strong>Apr/May</strong></div><div class="fomc-meeting__date">30-1</div>'
                '<div class="fomc-meeting__month"><strong>August</strong></div><div class="fomc-meeting__date">22 (notation vote)</div>'
                '<div class="fomc-meeting__month"><strong>June</strong></div><div class="fomc-meeting__date">15-16*</div>')
        self.assertEqual(M.parse_fomc(html), [{"date": "2027-05-01", "sep": False}, {"date": "2027-06-16", "sep": True}])

    def test_changed_page(self):
        with self.assertRaises(DataError):
            M.parse_fomc("<html>改版了</html>")


class Events(unittest.TestCase):
    def test_taipei_time(self):
        now = dt.datetime(2026, 10, 26, 8, 0, tzinfo=TPE)
        fomc = [{"date": "2026-10-28", "sep": False}, {"date": "2026-12-09", "sep": True}]
        manual = [{"date": "2026-11-10", "time": "08:30", "tz": "America/New_York", "kind": "cpi", "name": "美國 CPI（10 月）"},
                  {"date": "2026-12-17", "kind": "cbc", "name": "台灣央行理監事會"},
                  {"date": "2026-10-01", "time": "08:30", "tz": "America/New_York", "kind": "cpi", "name": "已經過了"}]
        ev = M.upcoming(now, fomc, manual, days=60)
        self.assertEqual([e["at"] for e in ev], ["2026-10-29T02:00+08:00", "2026-11-10T21:30+08:00",
                                                 "2026-12-10T03:00+08:00", "2026-12-17T23:59+08:00"])
        self.assertEqual(ev[2]["kind"], "fomc_sep")
        self.assertFalse(ev[3]["hasTime"])

    def test_events_file(self):
        """repo 裡的 events.json 要讀得進來（日期、時區格式正確）。"""
        problems = []
        ev = M._manual(problems)
        self.assertEqual(problems, [])
        self.assertTrue(ev)


class Read(unittest.TestCase):
    def test_sentences(self):
        t = {"sox": {"date": "2026-10-23", "chg1": 1.23, "chg20": -5.0, "ma50": -2.0}, "ixic": {"chg1": -0.5}, "spx": {"chg1": 0.0},
             "vix": {"last": 31.0}, "tnx": {"last": 4.5, "d20": 0.25}, "twd": {"last": 32.6, "chg20": 1.5},
             "wti": {"chg5": 8.0}, "gold": {"chg5": 1.0}}
        s = "".join(M.read(t, [("2026-10-22", 10.0), ("2026-10-23", 14.0)]))
        for x in ("費半 +1.2%", "跌破 50 日均線", "恐慌", "上升 0.25 個百分點", "新台幣近 20 日貶值 1.5%", "原油近 5 個交易日大漲 8.0%", "溢價 14.0%"):
            self.assertIn(x, s)
        self.assertNotIn("黃金", s)


class Update(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.meta, store.META = store.META, self.tmp.name
        store.save_meta("fomc", {"_saved": dt.date.today().isoformat(), "meetings": [{"date": "2026-10-28", "sep": False}]})

    def tearDown(self):
        store.META = self.meta
        self.tmp.cleanup()

    def fetch(self, url):
        name = {"%5ESOX": "SOX", "TSM": "TSM", "TWD%3DX": "TWD_X", "%5ETNX": "TNX", "CL%3DF": "CL_F", "%5EVIX": "SOX"}
        for k, v in name.items():
            if f"/chart/{k}?" in url:
                return chart(v)
        raise FetchError("404")

    def test_update(self):
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE)
        m, problems = M.update(now, {"2026-10-22": 1465.0, "2026-10-21": 1480.0}, fetch_json=self.fetch)
        self.assertEqual(len(problems), 1)  # VIX 拿到費半的數字，超出合理範圍
        self.assertIn("VIX", problems[0])
        self.assertIn("那斯達克", m["missing"])
        self.assertEqual(set(m["tiles"]), {"sox", "tsm", "twd", "tnx", "wti"})
        self.assertTrue(m["adr"])
        self.assertTrue(m["read"])
        later = now + dt.timedelta(hours=10)
        m2, _ = M.update(later, {"2026-10-22": 1465.0, "2026-10-21": 1480.0}, fetch_json=self.fetch)
        self.assertEqual(m2["asOf"], m["asOf"])  # 數字沒變，時間也不變（網頁不會多一次更新）

    def test_keeps_old_values(self):
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE)
        M.update(now, {}, fetch_json=self.fetch)

        def down(url):
            raise FetchError("timeout")
        m, problems = M.update(now + dt.timedelta(days=1), {}, fetch_json=down)
        self.assertEqual(problems, [])
        self.assertTrue(m["tiles"]["sox"]["stale"])


if __name__ == "__main__":
    unittest.main()
