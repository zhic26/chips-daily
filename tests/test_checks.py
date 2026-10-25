"""資料檢查：真實資料要能通過；常見的改版狀況（欄位錯位、單位改變、筆數變少）要被擋下來。"""
import copy
import unittest

import update
from chips.checks import DataError, check_day, check_picks
from tests.helpers import latest

DAY = latest("daily")
PICKS = latest("picks")


@unittest.skipIf(DAY is None, "repo 裡沒有每日資料")
class Day(unittest.TestCase):
    def broken(self, fn):
        ex = copy.deepcopy(DAY)
        fn(ex)
        with self.assertRaises(DataError):
            check_day(ex)

    def test_real_day_passes(self):
        self.assertTrue(check_day(copy.deepcopy(DAY)))

    def test_too_few_stocks(self):
        def drop(ex):
            keep = [c for c, r in ex["q"].items() if r[1] == "上市"][:300]
            ex["q"] = {c: r for c, r in ex["q"].items() if r[1] != "上市" or c in keep}
        self.broken(drop)

    def test_close_and_volume_swapped(self):
        def swap(ex):
            for r in ex["q"].values():
                r[2], r[7] = r[7], r[2]
        self.broken(swap)

    def test_amount_in_thousands(self):
        def shrink(ex):
            for r in ex["q"].values():
                if r[8]:
                    r[8] = r[8] / 1000
        self.broken(shrink)

    def test_inst_total_misaligned(self):
        def shift(ex):
            for v in ex["inst"].values():
                v[3] = v[0]
        self.broken(shift)

    def test_inst_in_lots(self):
        """單位從股變成張，買賣超會差 1000 倍（反過來變大就會大於成交量）。"""
        def grow(ex):
            for v in ex["inst"].values():
                v[:] = [x * 1000 for x in v]
        self.broken(grow)

    def test_margin_negative(self):
        def neg(ex):
            for v in ex["margin"].values():
                v[0] = -abs(v[0] or 1)
        self.broken(neg)

    def test_pending_not_checked(self):
        ex = copy.deepcopy(DAY)
        ex["margin"] = {}
        ex["pending"] = ["twse_margin", "tpex_margin"]
        self.assertTrue(check_day(ex))


@unittest.skipIf(PICKS is None, "repo 裡沒有名單")
class Picks(unittest.TestCase):
    cfg = update.load_cfg()

    def broken(self, fn):
        doc = copy.deepcopy(PICKS)
        fn(doc)
        with self.assertRaises(DataError):
            check_picks(doc, self.cfg)

    def test_real_picks_pass(self):
        self.assertTrue(check_picks(copy.deepcopy(PICKS), self.cfg))

    def test_rank_gap(self):
        self.broken(lambda d: d["picks"][1].update(rank=5))

    def test_score_order(self):
        self.broken(lambda d: d["picks"][0].update(score=1))

    def test_score_range(self):
        self.broken(lambda d: d["picks"][0].update(score=130))

    def test_duplicate(self):
        self.broken(lambda d: d["picks"].append(dict(d["picks"][0])))

    def test_nan_part(self):
        self.broken(lambda d: d["picks"][3]["parts"].update(revenue=float("nan")))


if __name__ == "__main__":
    unittest.main()
