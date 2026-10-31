"""實盤成績：名單在下一個平日開盤前固定、之後不改；滿 5／20 個交易日後的超額計算；滿 20 天後結果寫回檔案。"""
import datetime as dt
import json
import os
import tempfile
import unittest

from chips import store, track

TPE = dt.timezone(dt.timedelta(hours=8))
CFG = {"lookback_days": 5, "min_price": 10, "min_avg_lots": 1000}


def doc(date, model=5, codes=("1101", "2330")):
    return {"date": date, "model": model, "picks": [{"code": c, "market": "上市", "rank": i + 1, "score": 90 - i}
                                                      for i, c in enumerate(codes)]}


class Record(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data, store.DATA = store.DATA, self.tmp.name

    def tearDown(self):
        store.DATA = self.data
        self.tmp.cleanup()

    def test_lock_time(self):
        self.assertEqual(track.lock_at(dt.date(2026, 10, 23)), dt.datetime(2026, 10, 26, 9, 0, tzinfo=TPE))  # 週五 → 下週一
        self.assertEqual(track.lock_at(dt.date(2026, 10, 27)), dt.datetime(2026, 10, 28, 9, 0, tzinfo=TPE))

    def test_record_until_open(self):
        night = dt.datetime(2026, 10, 27, 22, 40, tzinfo=TPE)
        self.assertTrue(track.record(doc("2026-10-27"), night))
        self.assertFalse(track.record(doc("2026-10-27"), night))  # 一樣的名單不重寫
        self.assertTrue(track.record(doc("2026-10-27", codes=("1101", "2603")), night + dt.timedelta(hours=10)))  # 早上 8:40 還能更新
        self.assertFalse(track.record(doc("2026-10-27", model=6, codes=("9999",)), night + dt.timedelta(hours=11)))  # 開盤後就固定
        with open(os.path.join(self.tmp.name, "track", "2026-10-27.json"), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual([p[0] for p in saved["picks"]], ["1101", "2603"])
        self.assertEqual(saved["model"], 5)

    def test_backfilled_days_not_recorded(self):
        self.assertFalse(track.record(doc("2026-10-16"), dt.datetime(2026, 10, 25, 0, 30, tzinfo=TPE)))


class Results(unittest.TestCase):
    """假市場：上市 4 檔，每天 1101 漲 1%、2330 漲 2%、其他平盤；0050 每天漲 0.5%。連續 26 個交易日。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data, self.daily = store.DATA, store.DAILY
        store.DATA, store.DAILY = self.tmp.name, os.path.join(self.tmp.name, "daily")
        d, px = dt.date(2026, 9, 1), {"1101": 50.0, "2330": 1000.0, "2603": 200.0, "2002": 30.0, "0050": 100.0}
        self.days = []
        while len(self.days) < 26:
            if d.weekday() < 5:
                q = {}
                for c, p in px.items():
                    r = {"1101": 0.01, "2330": 0.02, "0050": 0.005}.get(c, 0.0)
                    new = round(p * (1 + r), 4)
                    q[c] = ["x", "上市", new, round(new - p, 4), new, new, new, 5_000_000, new * 5_000_000, 0]
                    px[c] = new
                etf = {"0050": q.pop("0050")}
                store.save_daily(d, {"date": d.isoformat(), "q": q, "etf": etf})
                self.days.append(d)
            d += dt.timedelta(days=1)

    def tearDown(self):
        store.DATA, store.DAILY = self.data, self.daily
        self.tmp.cleanup()

    def test_results_and_final(self):
        d0 = self.days[0].isoformat()
        night = dt.datetime.combine(self.days[0], dt.time(22, 40), tzinfo=TPE)
        track.record(doc(d0, codes=("1101", "2330")), night)
        track.record(doc(self.days[-3].isoformat()), dt.datetime.combine(self.days[-3], dt.time(22, 40), tzinfo=TPE))
        rows = track.results(CFG)
        self.assertEqual(len(rows), 2)
        r = rows[0]["result"]["上市"]
        self.assertTrue(rows[0]["final"])
        # 隔天開盤＝收盤，所以 5 日報酬是之後 4 天的漲幅
        self.assertAlmostEqual(r["avg5"], round(((1.01 ** 4 - 1) + (1.02 ** 4 - 1)) / 2 * 100, 2), places=1)
        self.assertGreater(r["avg5"], r["bench5"])
        self.assertEqual(r["beat20"], 100)
        self.assertNotIn("result", rows[1])  # 只過了 2 天
        with open(os.path.join(self.tmp.name, "track", d0 + ".json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["final"])  # 結果寫回檔案，之後每日資料清掉也還在
        s = track.summary(rows, CFG)
        self.assertEqual(s["lists"], 2)
        self.assertEqual(s["market"]["上市"]["n5"], 1)
        self.assertGreater(s["series"][0]["ex20"], 0)
        self.assertEqual(s["models"][0]["lists"], 2)
        # 0050 對照：一樣隔天開盤買，5 日是之後 4 天各漲 0.5%
        self.assertAlmostEqual(rows[0]["etf"]["5"], (1.005 ** 4 - 1) * 100, delta=0.02)  # 假資料每天四捨五入到小數 4 位
        self.assertAlmostEqual(s["market"]["上市"]["vs5"], r["avg5"] - rows[0]["etf"]["5"], places=1)
        self.assertEqual(s["market"]["上市"]["vsWin20"], 100)
        self.assertGreater(s["series"][0]["vs5"], 0)

    def test_etf_missing_day(self):
        """0050 少了任何一天的完整行情（例如還沒補抓的舊格式），就不拿來比。"""
        from chips.perf import etf_hold
        exs = {d: store.load_daily(d) for d in self.days}
        after = self.days[1:]
        self.assertIsNotNone(etf_hold(after, exs.get, 5))
        exs[after[2]] = dict(exs[after[2]], etf={"0050": ["元大台灣50", "上市", 100, 0.5]})  # 舊格式：沒有開盤價
        self.assertIsNone(etf_hold(after, exs.get, 5))
        self.assertIsNotNone(etf_hold(after, exs.get, 2))


if __name__ == "__main__":
    unittest.main()
