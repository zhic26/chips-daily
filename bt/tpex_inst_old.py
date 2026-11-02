"""櫃買三大法人 2018/1/12 以前是舊格式（16 欄、在第二個表），網站的解析看不懂。
這裡另外抓，存成 bt/tpex_inst_old/YYYY-MM-DD.json：{代號: [外資, 投信, 自營商, 合計]}（股數），沒資料存 {}。
用法：python bt/tpex_inst_old.py 起日 迄日"""
import datetime as dt
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from chips.net import get_json  # noqa: E402
from chips.sources import is_common_stock, z  # noqa: E402

OUT = "bt/tpex_inst_old"
URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={:%Y/%m/%d}&response=json"


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


def commit(tag):
    git("add", OUT)
    if git("commit", "-qm", f"櫃買法人舊格式 {tag}").returncode != 0:
        return
    for i in range(8):
        git("pull", "-q", "--rebase", "origin", "backtest")
        if git("push", "-q", "origin", "HEAD:backtest").returncode == 0:
            print("已存回", tag, flush=True)
            return
        time.sleep(5 + 7 * i)


def parse(j):
    for t in (j or {}).get("tables") or []:
        f = [str(x) for x in (t.get("fields") or [])]
        if len(f) == 16 and "三大法人" in f[-1] and "外資" in f[4] and "投信" in f[7] and "自營" in f[8]:
            out = {}
            for r in t.get("data") or []:
                c = str(r[0]).strip()
                if is_common_stock(c) and len(r) >= 16:
                    out[c] = [z(r[4]), z(r[7]), z(r[8]), z(r[15])]
            return out
    return {}


def main():
    s, e = (dt.date.fromisoformat(x) for x in sys.argv[1:3])
    os.makedirs(OUT, exist_ok=True)
    d, n = s, 0
    while d <= e:
        p = f"{OUT}/{d}.json"
        if d.weekday() < 5 and not os.path.exists(p):
            for attempt in range(3):
                try:
                    out = parse(get_json(URL.format(d), retries=3))
                    json.dump(out, open(p, "w"), separators=(",", ":"))
                    n += 1
                    print(d, len(out), flush=True)
                    break
                except Exception as ex:  # noqa: BLE001
                    print(d, "失敗", repr(ex)[:200], flush=True)
                    time.sleep(30)
            if n and n % 60 == 0:
                commit(str(d))
        d += dt.timedelta(days=1)
    commit(f"{s}～{e} 完成")


if __name__ == "__main__":
    main()
