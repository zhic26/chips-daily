"""官方網站回應的解析：用存下來的真實回應確認欄位對得上；欄位改名時要丟出 DataError，不能默默算錯。"""
import datetime as dt
import unittest

from chips import sources as S
from chips.checks import DataError
from tests.helpers import fake_web

D = dt.date(2026, 10, 22)


def rename_field(target, old, new):
    def edit(name, j):
        if name == target:
            for f in [j.get("fields")] + [t.get("fields") for t in j.get("tables") or []]:
                if f and old in f:
                    f[f.index(old)] = new
        return j
    return edit


class Daily(unittest.TestCase):
    def test_twse_inst(self):
        with fake_web():
            r = S.twse_inst(D)
        self.assertGreaterEqual(len(r), 10)
        for code, v in r.items():
            self.assertRegex(code, r"^[1-9]\d{3}$")
            self.assertAlmostEqual(v["foreign"] + v["trust"] + v["dealer"], v["total"], delta=max(abs(v["total"]) * 0.01, 1000))

    def test_twse_quotes(self):
        with fake_web():
            stocks, idx, stats = S.twse_quotes(D)
        self.assertGreaterEqual(len(stocks), 10)
        self.assertGreater(idx["加權指數"]["close"], 1000)
        self.assertGreater(stats["value"], 0)
        for v in stocks.values():
            if None not in (v["close"], v["high"], v["low"]):
                self.assertLessEqual(v["low"], v["close"])
                self.assertLessEqual(v["close"], v["high"])

    def test_etf_prices(self):
        """ETF 收盤價只放進 etf，不會混進計分用的個股；沒傳 etf 時行為不變。"""
        with fake_web():
            tw, tp = {}, {}
            stocks, _, _ = S.twse_quotes(D, etf=tw)
            plain, _, _ = S.twse_quotes(D)
            otc = S.tpex_quotes(D, etf=tp)
        self.assertEqual(set(stocks), set(plain))
        for etf, quotes in ((tw, stocks), (tp, otc)):
            self.assertTrue(etf)
            self.assertFalse(set(etf) & set(quotes))
            for code, v in etf.items():
                self.assertTrue(S.is_etf(code), code)
                self.assertTrue(v["name"])
                self.assertTrue(v["close"] is None or v["close"] > 0)
                if None not in (v["close"], v["open"], v["high"], v["low"]):  # 欄位跟個股一樣，0050 對照要用開盤價
                    self.assertLessEqual(v["low"], min(v["open"], v["close"]))
                    self.assertGreaterEqual(v["high"], max(v["open"], v["close"]))
        self.assertTrue(S.is_etf("0050") and S.is_etf("006208") and S.is_etf("00679B"))
        self.assertFalse(S.is_etf("2330") or S.is_etf("0050A1"))

    def test_fill_etf(self):
        from chips import daily
        ex = {"date": D.isoformat(), "pending": [], "q": {}}
        with fake_web():
            self.assertTrue(daily.fill_etf(D, ex))
            self.assertFalse(daily.fill_etf(D, ex))  # 已經有了就不再抓
        markets = {r[1] for r in ex["etf"].values()}
        self.assertEqual(markets, {"上市", "上櫃"})
        self.assertTrue(all(len(r) == 10 for r in ex["etf"].values()))  # 跟個股的 q 同格式
        self.assertFalse(daily.fill_etf(D, {"light": True}))
        old = {"date": D.isoformat(), "pending": [], "q": {}, "etf": {"0050": ["元大台灣50", "上市", 100, 0.5]}}
        with fake_web():
            self.assertTrue(daily.fill_etf(D, old))  # 10/30 以前存的舊格式（沒有開盤價）要重抓
        self.assertTrue(daily.etf_full(old))

    def test_twse_margin(self):
        def more_rows(name, j):  # 樣本只留了 25 列，解析時要求超過 50 列才算完整
            if name == "twse_MI_MARGN":
                j["tables"][1]["data"] *= 3
            return j
        with fake_web(more_rows):
            r, summary = S.twse_margin(D)
        self.assertGreaterEqual(len(r), 10)
        self.assertTrue(all(v["mBal"] >= 0 and v["sBal"] >= 0 for v in r.values()))
        self.assertGreater(summary["amt"], 0)

    def test_tpex(self):
        with fake_web():
            inst, quotes, margin = S.tpex_inst(D), S.tpex_quotes(D), S.tpex_margin(D)
        for r in (inst, quotes, margin):
            self.assertGreaterEqual(len(r), 10)
        for v in inst.values():
            self.assertAlmostEqual(v["foreign"] + v["trust"] + v["dealer"], v["total"], delta=max(abs(v["total"]) * 0.01, 1000))
        for v in quotes.values():
            if None not in (v["close"], v["high"], v["low"]):
                self.assertLessEqual(v["low"], v["close"])
                self.assertLessEqual(v["close"], v["high"])


    def test_fixed_columns_moved(self):
        """用固定位置解析的表，欄位順序一變就要報錯。"""
        def shift(name, j):
            if name in ("tpex_insti", "tpex_margin"):
                f = j["tables"][0]["fields"]
                f.insert(3, "新欄位")
                f.pop()
            return j
        with fake_web(shift):
            for call in (lambda: S.tpex_inst(D), lambda: S.tpex_margin(D)):
                with self.assertRaises(DataError):
                    call()


class Alerts(unittest.TestCase):
    def test_notice(self):
        with fake_web():
            tw = S.twse_notice(D, D)
            tp = S.tpex_notice(dt.date(2026, 10, 15), dt.date(2026, 10, 16))
        self.assertEqual(list(tw), ["2026-10-22"])
        self.assertIn("2033", tw["2026-10-22"])
        self.assertNotIn("047046", tw["2026-10-22"])  # 權證不收
        self.assertEqual(sorted(tp), ["2026-10-15", "2026-10-16"])
        for day in list(tw.values()) + list(tp.values()):
            for why in day.values():
                self.assertTrue(0 < len(why) <= 45)
                self.assertNotIn("<", why)
                self.assertNotIn("款", why[-4:])

    def test_punish(self):
        with fake_web():
            rows = S.twse_punish(dt.date(2026, 10, 1), D) + S.tpex_punish(dt.date(2026, 10, 1), D)
        self.assertGreater(len(rows), 10)
        for p in rows:
            self.assertRegex(p["code"], r"^[1-9]\d{3}$")
            self.assertLessEqual(p["ann"], p["start"])
            self.assertLessEqual(p["start"], p["end"])
            self.assertTrue(p["step"])
        self.assertIn({"code": "3287", "ann": "2026-10-21", "start": "2026-10-22", "end": "2026-10-29"},
                      [{k: p[k] for k in ("code", "ann", "start", "end")} for p in rows])

    def test_tpex_ignores_dates(self):
        """櫃買中心若不理會查詢日期（回傳別的範圍），不能把別天的資料當成這幾天的。"""
        def edit(name, j):
            j["date"] = "20261022~20261025"
            return j
        with fake_web(edit), self.assertRaises(DataError):
            S.tpex_notice(dt.date(2026, 10, 15), dt.date(2026, 10, 16))

    def test_renamed_fields(self):
        cases = [("twse_notice", "證券代號", lambda: S.twse_notice(D, D)),
                 ("twse_punish", "處置起迄時間", lambda: S.twse_punish(D, D)),
                 ("tpex_attention", "公告日期", lambda: S.tpex_notice(dt.date(2026, 10, 15), dt.date(2026, 10, 16))),
                 ("tpex_disposal", "公布日期", lambda: S.tpex_punish(D, D))]
        for target, field, call in cases:
            with self.subTest(target), fake_web(rename_field(target, field, "舊" + field)), self.assertRaises(DataError):
                call()

    def test_no_rows(self):
        def edit(name, j):
            if "data" in j:
                j["data"], j["stat"] = [], "很抱歉，沒有符合條件的資料!"
            for t in j.get("tables") or []:
                t["data"] = []
            return j
        with fake_web(edit):
            self.assertEqual(S.twse_notice(D, D), {})
            self.assertEqual(S.tpex_punish(D, D), [])

    def test_roc_helpers(self):
        self.assertEqual(S._roc_date("115.10.22"), D)
        self.assertEqual(S._roc_date("1151022"), D)
        self.assertEqual(S._period("115/10/20～115/10/27"), (dt.date(2026, 10, 20), dt.date(2026, 10, 27)))
        self.assertEqual(S._measure("（約每二十分鐘撮合一次）收取全部之買進價金"), (20, True))
        self.assertEqual(S._measure("(約每5分鐘撮合一次)"), (5, False))


if __name__ == "__main__":
    unittest.main()
