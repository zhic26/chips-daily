"""交易日曆：證交所開休市表的解析，以及「下一個交易日」「第 N 個交易日」的推算。"""
import datetime as dt
import json
import os
import unittest

from chips import tcal
from chips.checks import DataError
from tests.helpers import FIX

with open(os.path.join(FIX, "twse_holiday_2026.json"), encoding="utf-8") as f:
    Y = {"2026": tcal.parse(json.load(f))}


class Calendar(unittest.TestCase):
    def test_parse(self):
        self.assertIn("2026-10-26", Y["2026"])      # 光復節補假
        self.assertNotIn("2026-01-02", Y["2026"])   # 開始交易日不是休市
        self.assertNotIn("2026-02-11", Y["2026"])   # 封關日有交易
        with self.assertRaises(DataError):
            tcal.parse({"stat": "改版"})

    def test_next_day(self):
        self.assertEqual(tcal.nth_trading_day(dt.date(2026, 10, 22), 1, Y, ["2026-10-23"]), (dt.date(2026, 10, 27), False))
        self.assertEqual(tcal.nth_trading_day(dt.date(2026, 2, 10), 2, Y), (dt.date(2026, 2, 23), False))  # 春節

    def test_unknown_year(self):
        d, approx = tcal.nth_trading_day(dt.date(2026, 12, 30), 3, Y)
        self.assertEqual(d, dt.date(2027, 1, 4))
        self.assertTrue(approx)


if __name__ == "__main__":
    unittest.main()
