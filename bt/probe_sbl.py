"""存下證交所、櫃買中心借券賣出餘額的原始回應（網站要加借券資料，測試樣本用；2026-11-09）。"""
import os
import subprocess
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
os.makedirs("bt/probe", exist_ok=True)
for name, url in [("twse_TWT93U_20261106", "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=20261106&response=json"),
                  ("tpex_sbl_20261106", "https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=2026/11/06&response=json"),
                  ("twse_TWT93U_20261108", "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=20261108&response=json"),
                  ("tpex_sbl_20261108", "https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=2026/11/08&response=json")]:
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                t = r.read().decode("utf-8", "replace")
            break
        except Exception as e:  # noqa: BLE001
            t = f"ERROR {e!r}"
            time.sleep(10)
    open(f"bt/probe/{name}.json", "w", encoding="utf-8").write(t)
    print(name, len(t), t[:200].replace("\n", " "), flush=True)
    time.sleep(4)
subprocess.run(["git", "add", "bt/probe"])
subprocess.run(["git", "commit", "-qm", "借券原始回應樣本"])
for i in range(10):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
        break
    time.sleep(5 + 5 * i)
