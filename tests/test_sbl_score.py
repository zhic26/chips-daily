"""第 8 版的借券賣出分數：越少分數越高、查不到給中間值、還沒公布時這一項不計分。"""
import unittest

from chips import model

CFG = {"crowding": {"margin_5d_pct": [10, 20], "margin_min_lots": 300, "runup_20d_pct": [30, 50], "points": [5, 10],
                    "max_penalty": 15, "deduct": False},
       "tdcc_candidates": 40, "max_big_pct": 99, "top_n": 20,
       "weights": {"inst_today": 0, "inst_5d": 0, "consistency": 40, "big_holders": 15, "margin": 0, "revenue": 30, "sbl": 15}}


class NoBig:
    full = True

    def __call__(self, codes):
        return {}


def row(code, sbl_days):
    return {"code": code, "instNet": 100, "_avg": 1000, "inst5d": 300, "_n": 5, "foreignDays": 3, "trustDays": 1,
            "marginAdd5": 0, "marginUp5": None, "ret20": 0, "rev3": 10, "sblDays": sbl_days}


class SblScore(unittest.TestCase):
    def test_less_is_better(self):
        rows = [row("1101", 0.1), row("2330", 5.0), row("2317", None)]
        got = {x["code"]: x["parts"]["sbl"] for x in model.score_market(rows, CFG["weights"], NoBig(), CFG)}
        self.assertEqual(got, {"1101": 15.0, "2330": 0.0, "2317": 7.5})  # 不能借券賣出（不在表上）給中間值

    def test_ties_share_rank(self):
        rows = [row("1101", 0.0), row("1102", 0.0), row("2330", 3.0)]
        got = {x["code"]: x["parts"]["sbl"] for x in model.score_market(rows, CFG["weights"], NoBig(), CFG)}
        self.assertEqual(got["1101"], got["1102"])
        self.assertGreater(got["1101"], got["2330"])

    def test_pending_rescales(self):
        w = model.weights_for(CFG, True, sbl_ok=False)
        self.assertEqual(w["sbl"], 0)
        self.assertAlmostEqual(sum(w.values()), 100)
        self.assertAlmostEqual(w["consistency"], 40 * 100 / 85)
        self.assertEqual(model.weights_for(CFG, True), CFG["weights"])

    def test_ready(self):
        self.assertFalse(model.sbl_ready({"pending": []}, "上市"))  # 借券上線前存的日子
        e0 = {"pending": ["tpex_sbl"], "sbl": {"2330": [1000, 10]}}
        self.assertTrue(model.sbl_ready(e0, "上市"))
        self.assertFalse(model.sbl_ready(e0, "上櫃"))

    def test_reason(self):
        base = {"instNet": 1, "foreignNet": 1, "trustNet": 0, "dealerNet": 0, "inst5d": 0, "avgVol": 100}
        self.assertIn("借券賣出餘額 1,234 張，約 2.5 天的成交量", model.reason_for(dict(base, sblBal=1234, sblDays=2.47)))
        self.assertIn("沒有借券賣出餘額", model.reason_for(dict(base, sblBal=0, sblDays=0.0)))
        self.assertNotIn("借券", model.reason_for(dict(base, sblBal=None, sblDays=None)))


if __name__ == "__main__":
    unittest.main()
