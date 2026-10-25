"""網頁：用 repo 裡的真實資料產生一次，確認資料有嵌進去、JavaScript 沒有語法錯誤。"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import update
from chips import site, store


@unittest.skipUnless(store.picks_dates(), "repo 裡沒有名單")
class Build(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            real, site.DOCS = site.DOCS, tmp
            try:
                site.build(update.load_cfg(), dt.datetime(2026, 10, 22, 22, 40))
            finally:
                site.DOCS = real
            html = open(os.path.join(tmp, "index.html"), encoding="utf-8").read()
            latest = json.load(open(os.path.join(tmp, "latest.json"), encoding="utf-8"))
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertNotIn("__TITLE__", html)
        self.assertTrue(latest["picks"])
        if shutil.which("node"):
            for i, js in enumerate(re.findall(r"<script>(.*?)</script>", html, flags=re.S)):
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                    f.write(js)
                r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
                os.unlink(f.name)
                self.assertEqual(r.returncode, 0, f"第 {i + 1} 段 script 語法錯誤：{r.stderr[:300]}")


if __name__ == "__main__":
    unittest.main()
