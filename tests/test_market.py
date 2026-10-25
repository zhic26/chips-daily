"""大盤體溫新增的兩項：櫃買指數月表、外資台指期未平倉（期交所 CSV），以及描述文字。"""
import datetime as dt
import os
import unittest

from chips import model
from chips import sources as S
from chips.checks import DataError
from tests.helpers import FIX, fake_web


def taifex_text():
    with open(os.path.join(FIX, "taifex_fut.csv"), "rb") as f:
        return f.read().decode("cp950")


class Sources(unittest.TestCase):
    def test_taifex(self):
        got = S.parse_taifex_fut(taifex_text())
        self.assertEqual(len(got), 21)
        self.assertEqual(got["2026-10-22"], {"net": -87297, "long": 8126, "short": 95423})
        for v in got.values():
            self.assertEqual(v["long"] - v["short"], v["net"])

    def test_taifex_changed(self):
        with self.assertRaises(DataError):
            S.parse_taifex_fut(taifex_text().replace("多空未平倉口數淨額", "淨額"))
        self.assertEqual(S.parse_taifex_fut(taifex_text().splitlines()[0]), {})  # 只有表頭（還沒公布）

    def test_taifex_html(self):
        real = S.fetch
        S.fetch = lambda url, data=None, **kw: "<html><body>系統維護中</body></html>".encode()
        try:
            with self.assertRaises(DataError):
                S.taifex_foreign_oi(dt.date(2026, 10, 1), dt.date(2026, 10, 22))
        finally:
            S.fetch = real

    def test_otc_month(self):
        with fake_web():
            m = S.tpex_index_month(dt.date(2026, 9, 15))
            one = S.tpex_index(dt.date(2026, 9, 2))
        self.assertEqual(len(m), 20)
        self.assertEqual(m["2026-09-01"]["close"], 410.77)
        self.assertEqual(one, {"close": 406.96, "chg": -3.81, "chgPct": -0.93})


class Read(unittest.TestCase):
    def base(self):
        return {"value": {"ratio": None}, "taiexChg": None, "margin": {"chg": None}, "breadth": {"上市": {"pct": None}}}

    def test_sentences(self):
        t = dict(self.base(), otc={"today": -3.47, "taiex": -1.81, "rel20": -4.2}, futures={"net": -87297, "chg": -1225})
        s = "".join(model.temp_read(t))
        self.assertIn("櫃買指數 −3.47%、加權指數 −1.81%", s)
        self.assertIn("櫃買比加權弱 4.2 個百分點，資金偏向權值股", s)
        self.assertIn("外資台指期淨空單 87,297 口，比前一天增加 1,225 口", s)
        t["futures"] = {"net": -80000, "chg": 7297}
        self.assertIn("比前一天減少 7,297 口", "".join(model.temp_read(t)))


if __name__ == "__main__":
    unittest.main()
