"""參考出場規則：分數掉到第 N 名以後隔天開盤賣、最多抱 M 天、今天觸發就顯示「明天賣」、沒觸發就是持有中。"""
import datetime as dt
import os
import tempfile
import unittest

from chips import exits, site, store

CFG = {"exit": {"rank": 2, "max_days": 6}}


class Rule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = store.DATA, store.DAILY, store.PICKS
        store.DATA = self.tmp.name
        store.DAILY, store.PICKS = os.path.join(self.tmp.name, "daily"), os.path.join(self.tmp.name, "picks")
        d, self.days, px = dt.date(2026, 9, 1), [], {"A": 100.0, "B": 50.0, "C": 20.0}
        while len(self.days) < 10:
            if d.weekday() < 5:
                q = {}
                for c in px:
                    o = px[c]
                    px[c] = round(o * 1.01, 4)  # 每天開盤 o、收盤漲 1%
                    q[c] = ["x", "上市", px[c], round(px[c] - o, 4), o, px[c], o, 5_000_000, 0, 0]
                store.save_daily(d, {"date": d.isoformat(), "q": q})
                self.days.append(d)
            d += dt.timedelta(days=1)
        # 第 0 天的名單選了 A、B；排名：第 0～2 天 A、B 都在前 2 名，第 3 天 B 掉到第 3 名
        for i, day in enumerate(self.days):
            rk = ["A", "B", "C"] if i != 3 else ["A", "C", "B"]
            store.save_picks(day, {"date": day.isoformat(), "picks": [{"code": "A", "market": "上市", "name": "甲", "rank": 1},
                                                                         {"code": "B", "market": "上市", "name": "乙", "rank": 2}] if i == 0 else [],
                                   "ranking": {"上市": rk}})

    def tearDown(self):
        store.DATA, store.DAILY, store.PICKS = self.saved
        self.tmp.cleanup()

    def run_until(self, n):
        stored = self.days[:n]
        cache = {}

        def exf(d):
            if d not in cache:
                cache[d] = store.load_daily(d)
            return cache[d]
        return exits.evaluate(CFG, [self.days[0]], stored, exf)

    def test_sold_on_rank_drop(self):
        st = self.run_until(10)
        b = st[(self.days[0].isoformat(), "B")]
        self.assertEqual((b["state"], b["why"], b["exit"]), ("sold", "rank", self.days[4].isoformat()))  # 第 3 天收盤掉出 → 第 4 天開盤賣
        # 第 1 天開盤買、到第 4 天開盤：第 1、2、3 天各漲 1%（第 4 天開盤＝第 3 天收盤）
        self.assertAlmostEqual(b["ret"], round((1.01 ** 3 - 1) * 100, 2), places=1)

    def test_pending_sell(self):
        st = self.run_until(4)  # 最新一天就是第 3 天：今天觸發，明天開盤賣
        self.assertEqual(st[(self.days[0].isoformat(), "B")]["state"], "sell")
        self.assertEqual(st[(self.days[0].isoformat(), "A")]["state"], "holding")
        self.assertEqual(st[(self.days[0].isoformat(), "A")]["rank"], 1)

    def test_sell_shows_market_average(self):
        """明天要賣的股票附上同一段期間同市場的平均；三檔漲法一樣，平均就等於這一檔的報酬。持有中的不附。"""
        for d in self.days[4:]:  # 只留前 4 天：第 3 天收盤觸發
            os.remove(os.path.join(store.DAILY, d.isoformat() + ".json"))
            os.remove(os.path.join(store.PICKS, d.isoformat() + ".json"))
        _, items = site.exit_status(dict(CFG, lookback_days=1, min_avg_lots=1000, min_price=10))
        b = next(x for x in items if x["code"] == "B")
        self.assertEqual(b["state"], "sell")
        self.assertAlmostEqual(b["bench"], b["ret"], places=2)
        self.assertAlmostEqual(b["ret"], round((1.01 ** 3 - 1) * 100, 2), places=2)
        self.assertNotIn("bench", next(x for x in items if x["code"] == "A"))

    def test_items_keep_list_position(self):
        """每一筆帶著它在當天名單上的名次（pos），網頁靠這個只列前 10 名；rank 是現在的名次，兩個分開。"""
        for d in self.days[4:]:
            os.remove(os.path.join(store.DAILY, d.isoformat() + ".json"))
            os.remove(os.path.join(store.PICKS, d.isoformat() + ".json"))
        _, items = site.exit_status(dict(CFG, lookback_days=1, min_avg_lots=1000, min_price=10))
        by = {x["code"]: x for x in items}
        self.assertEqual((by["A"]["pos"], by["B"]["pos"]), (1, 2))
        self.assertEqual(by["B"]["rank"], 3)  # 第 3 天掉到第 3 名

    def test_max_days(self):
        a = self.run_until(10)[(self.days[0].isoformat(), "A")]
        self.assertEqual((a["state"], a["why"], a["exit"], a["days"]), ("sold", "max", self.days[6].isoformat(), 6))
        self.assertAlmostEqual(a["ret"], round((1.01 ** 6 - 1) * 100, 2), places=1)


if __name__ == "__main__":
    unittest.main()
