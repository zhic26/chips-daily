"""存檔：第一次存到還不存在的資料夾也要成功（集保週資料曾因此一直沒存到）。"""
import os
import tempfile
import unittest

from chips import store


class Write(unittest.TestCase):
    def test_new_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            real, store.DATA = store.DATA, tmp
            try:
                self.assertTrue(store.save_tdcc_full("20261022", {"2330": [1, 2, 3, 4]}))
                self.assertFalse(store.save_tdcc_full("20261022", {"2330": [9, 9, 9, 9]}))  # 已存過不覆蓋
                store.save_revenue("2026-09", {"2330": [1, 2]})
            finally:
                store.DATA = real
            self.assertTrue(os.path.exists(os.path.join(tmp, "tdcc_full", "20261022.json")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "revenue", "2026-09.json")))


if __name__ == "__main__":
    unittest.main()
