"""VIX、S&P 500、加權指數、那斯達克的完整日線（Yahoo chart API，range=max）。
起因：使用者 2026-11-23 想驗證 Threads 上流傳的「VIX 接近 30 買股票勝率很高、彈到 40 很難輸錢」（說是股癌講的）。
存成 bt/vix_hist/<代號>.json：[[日期(台北時間的日期字串), 收盤], ...]；_status.json 記結果。"""
import datetime as dt
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

OUT = "bt/vix_hist"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
os.makedirs(OUT, exist_ok=True)
st = {}
for sym, tz in (("^VIX", "America/New_York"), ("^GSPC", "America/New_York"), ("^IXIC", "America/New_York"), ("^TWII", "Asia/Taipei")):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=max&interval=1d"
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90) as r:
            j = json.loads(r.read())
        res = j["chart"]["result"][0]
        off = res["meta"].get("gmtoffset", 0)
        rows = []
        for ts, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
            if c is None:
                continue
            d = (dt.datetime.utcfromtimestamp(ts + off)).date().isoformat()  # 交易所當地日期
            rows.append([d, round(c, 4)])
        json.dump(rows, open(f"{OUT}/{sym.replace('^', '')}.json", "w"))
        st[sym] = f"ok {len(rows)} 筆 {rows[0][0]}～{rows[-1][0]}"
    except Exception as e:  # noqa: BLE001
        st[sym] = repr(e)[:200]
    print(sym, st[sym], flush=True)
    time.sleep(3)
json.dump(st, open(f"{OUT}/_status.json", "w"), ensure_ascii=False, indent=1)
subprocess.run(["git", "add", OUT])
subprocess.run(["git", "commit", "-qm", "VIX、S&P 500、那斯達克、加權指數完整日線"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
        break
    time.sleep(5)
