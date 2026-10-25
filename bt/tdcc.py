"""回測用：集保「股權分散表查詢」逐檔逐週抓完整分級表。
用法：python bt/tdcc.py probe            只抓可查詢的週別清單並試查兩檔
      python bt/tdcc.py run 工作清單檔 輸出檔   清單每行「代號 週別YYYYMMDD」"""
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from chips.net import FetchError, decode, fetch  # noqa: E402
from chips import net  # noqa: E402

net.MIN_GAP["www.tdcc.com.tw"] = 1.0  # 回測大量查詢：放慢一點，避免造成集保網站負擔

URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"


class Tdcc:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.token, self.weeks = None, []

    def _absorb(self, html):
        w = re.findall(r'<option[^>]*value="(\d{8})"', html)
        if w:
            self.weeks = w
        m = re.search(r'name="SYNCHRONIZER_TOKEN"[^>]*value="([^"]+)"', html)
        self.token = m.group(1) if m else None

    def refresh(self):
        self._absorb(decode(fetch(URL, opener=self.opener, retries=4)))
        if not self.token:
            raise FetchError("找不到 token")

    def table(self, code, week):
        """回傳 {級距: [人數, 股數, 比例%]}；查無資料回傳 {}。"""
        for attempt in range(3):
            if not self.token:
                self.refresh()
            form = {"SYNCHRONIZER_TOKEN": self.token, "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
                    "method": "submit", "firDate": self.weeks[0] if self.weeks else week, "scaDate": week,
                    "sqlMethod": "StockNo", "stockNo": code, "stockName": ""}
            html = decode(fetch(URL, data=form, opener=self.opener, retries=4))
            self._absorb(html)
            rows = {}
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S):
                cells = [re.sub(r"<[^>]+>|&nbsp;|,", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
                if len(cells) >= 5 and cells[0].isdigit():
                    try:
                        rows[int(cells[0])] = [float(cells[2] or 0), float(cells[3] or 0), float(cells[4] or 0)]
                    except ValueError:
                        pass
            if rows:
                return rows
            if "查無" in html or "無資料" in html:
                return {}
            self.token = None  # 可能 token 失效，重拿一次
        return {}


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


def save(paths, tag):
    git("add", *paths)
    if git("commit", "-qm", f"集保 {tag}").returncode != 0:
        return
    for i in range(10):
        git("pull", "-q", "--rebase", "origin", "backtest")
        if git("push", "-q", "origin", "HEAD:backtest").returncode == 0:
            return
        time.sleep(5 + 5 * i)


def main():
    t = Tdcc()
    if sys.argv[1] == "probe":
        t.refresh()
        os.makedirs("bt/tdcc", exist_ok=True)
        out = {"weeks": t.weeks, "samples": {}}
        for code, week in (("2330", t.weeks[0]), ("2330", t.weeks[-1]), ("3293", t.weeks[3])):
            out["samples"][f"{code}_{week}"] = t.table(code, week)
        json.dump(out, open("bt/tdcc/probe.json", "w"), ensure_ascii=False)
        print(len(t.weeks), t.weeks[:3], t.weeks[-3:], json.dumps(out["samples"], ensure_ascii=False)[:600])
        save(["bt/tdcc/probe.json"], "probe")
        return
    jobs = [ln.split() for ln in open(sys.argv[2]) if ln.strip()]
    out = sys.argv[3]
    done = set()
    if os.path.exists(out):
        for ln in open(out):
            r = json.loads(ln)
            done.add((r["c"], r["w"]))
    t.refresh()
    n, t0 = 0, time.time()
    with open(out, "a") as fh:
        for code, week in jobs:
            if (code, week) in done:
                continue
            try:
                tab = t.table(code, week)
            except FetchError as e:
                print(code, week, "失敗", e, flush=True)
                time.sleep(30)
                t.token = None
                continue
            fh.write(json.dumps({"c": code, "w": week, "t": tab}, separators=(",", ":")) + "\n")
            n += 1
            if n % 200 == 0:
                fh.flush()
                print(n, "筆", f"{(time.time() - t0) / n:.2f} 秒/筆", flush=True)
                save([out], f"{os.path.basename(out)} {n}")
    save([out], f"{os.path.basename(out)} 完成")


if __name__ == "__main__":
    main()
