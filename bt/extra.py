"""回測用：證交所除權除息計算結果表（TWT49U），算除權息當天的真實漲跌用。"""
import datetime as dt
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from chips.net import get_json  # noqa: E402

os.makedirs("bt/extra", exist_ok=True)
d = dt.date(2024, 6, 1)
while d <= dt.date(2026, 10, 31):
    nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    end = nxt - dt.timedelta(days=1)
    url = (f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json"
           f"&startDate={d:%Y%m%d}&endDate={end:%Y%m%d}")
    try:
        j = get_json(url)
        n = len(j.get("data") or []) if isinstance(j, dict) else 0
        json.dump(j, open(f"bt/extra/twt49u_{d:%Y%m}.json", "w"), ensure_ascii=False)
        print(d, "筆數", n, (j.get("fields") if n and d.month == 6 else ""), flush=True)
    except Exception as e:
        print(d, "失敗", e, flush=True)
    d = nxt
subprocess.run(["git", "add", "bt/extra"])
subprocess.run(["git", "commit", "-qm", "除權息參考價"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
        break
