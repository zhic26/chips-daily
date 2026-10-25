"""注意股、處置股：連續天數、處置期間的判斷，存檔規則，以及名單上的標籤文字。"""
import datetime as dt
import os
import tempfile
import unittest

from chips import alerts as A
from chips import model, store
from chips.checks import DataError
from chips.net import FetchError

D = dt.date
TPE = dt.timezone(dt.timedelta(hours=8))
DAYS = [D(2026, 10, 22), D(2026, 10, 21), D(2026, 10, 20), D(2026, 10, 19), D(2026, 10, 16)]


def al(notice_tw, punish_tw=()):
    return {"notice": {"twse": notice_tw, "tpex": {d.isoformat(): {} for d in DAYS}}, "punish": {"twse": list(punish_tw), "tpex": []}}


class ForDay(unittest.TestCase):
    def test_streak(self):
        a = al({"2026-10-22": {"2330": "漲幅大"}, "2026-10-21": {"2330": "x"}, "2026-10-20": {"2330": "x"},
                "2026-10-19": {}, "2026-10-16": {"2330": "x"}})
        out, missing = A.for_day(a, D(2026, 10, 22), DAYS)
        self.assertEqual(out["2330"], {"notice": 3, "why": "漲幅大"})
        self.assertEqual(missing, [])
        out, _ = A.for_day(a, D(2026, 10, 21), DAYS)
        self.assertEqual(out["2330"]["notice"], 2)

    def test_missing_day(self):
        out, missing = A.for_day(al({}), D(2026, 10, 22), DAYS)
        self.assertEqual(missing, ["上市"])

    def test_punish_window(self):
        p = {"code": "2330", "ann": "2026-10-20", "start": "2026-10-21", "end": "2026-10-22", "step": "第一次處置", "mins": 5, "prepay": True}
        a = al({d.isoformat(): {} for d in DAYS}, [p])
        self.assertNotIn("2330", A.for_day(a, D(2026, 10, 19), DAYS)[0])  # 還沒公布
        self.assertIn("punish", A.for_day(a, D(2026, 10, 20), DAYS)[0]["2330"])  # 公布當天收盤後
        self.assertIn("punish", A.for_day(a, D(2026, 10, 21), DAYS)[0]["2330"])
        self.assertNotIn("2330", A.for_day(a, D(2026, 10, 22), DAYS)[0])  # 最後一天收盤後已結束


class Update(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.meta, store.META = store.META, self.tmp.name
        self.markets = A.MARKETS

    def tearDown(self):
        store.META, A.MARKETS = self.meta, self.markets
        self.tmp.cleanup()

    def run_with(self, tw_notice, tp_notice, now):
        def punish(a, b):
            return [{"code": "2330", "ann": "2026-10-21", "start": "2026-10-22", "end": "2026-10-29", "step": "第一次處置", "mins": 5, "prepay": True}]
        A.MARKETS = (("twse", "上市", tw_notice, punish), ("tpex", "上櫃", tp_notice, punish))
        return A.update(DAYS[:2], now)

    def test_saves_only_final_days(self):
        early = dt.datetime(2026, 10, 22, 15, 0, tzinfo=TPE)
        a, problems = self.run_with(lambda s, e: {"2026-10-22": {"2330": "x"}}, lambda s, e: {}, early)
        self.assertEqual(problems, [])
        self.assertIn("2330", a["notice"]["twse"]["2026-10-22"])  # 這次照用
        saved = store.load_meta("alerts")
        self.assertNotIn("2026-10-22", saved["notice"]["twse"])  # 但不存，晚上再抓
        self.assertIn("2026-10-21", saved["notice"]["twse"])

    def test_errors(self):
        late = dt.datetime(2026, 10, 22, 22, 40, tzinfo=TPE)

        def down(s, e):
            raise FetchError("timeout")

        def changed(s, e):
            raise DataError("改版")
        a, problems = self.run_with(down, changed, late)
        self.assertEqual(problems, ["改版"])  # 連線失敗不算問題，格式錯誤才算
        out, missing = A.for_day(a, DAYS[0], DAYS)
        self.assertEqual(missing, ["上市", "上櫃"])
        self.assertIn("punish", out["2330"])


class Tags(unittest.TestCase):
    base = {"trustStreak": 0, "foreignStreak": 0, "inst5d": 0, "avgVol": 100, "chgPct": 0, "instNet": 1,
            "foreignNet": 1, "trustNet": 0, "dealerNet": 0}

    def test_tags_and_reason(self):
        x = dict(self.base, alert={"notice": 2, "why": "最近六個營業日累積收盤價漲幅達33.04%"})
        self.assertEqual(model.tags_for(x)[0], "連續注意 2 天")
        self.assertIn("已連續 2 個交易日", model.reason_for(x))
        x = dict(self.base, alert={"notice": 1, "why": "x", "punish": {"start": "2026-10-22", "end": "2026-10-29", "step": "第一次處置", "mins": 5, "prepay": True}})
        self.assertEqual(model.tags_for(x)[0], "處置中")
        r = model.reason_for(x)
        self.assertTrue(r.startswith("處置股（第一次處置，10/22～10/29）"))
        self.assertIn("約每 5 分鐘撮合一次", r)
        self.assertEqual(model.tags_for(dict(self.base))[:1], [])


if __name__ == "__main__":
    unittest.main()
