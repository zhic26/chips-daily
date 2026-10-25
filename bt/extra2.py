"""回測補充資料：月營收（公開資訊觀測站彙總表）與證交所借券賣出餘額（TWT93U）。
用法：python bt/extra2.py rev            抓 2023/06～2026/09 每月營收
      python bt/extra2.py sbl 第幾份 共幾份  抓回測期間每個交易日的借券賣出"""
import csv
import datetime as dt
import glob
import gzip
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from chips.net import fetch, get_json  # noqa: E402

OUT = "bt/extra2"
os.makedirs(OUT, exist_ok=True)


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


def save(paths, tag):
    git("add", *paths)
    if git("commit", "-qm", tag).returncode != 0:
        return
    for i in range(10):
        git("pull", "-q", "--rebase", "origin", "backtest")
        if git("push", "-q", "origin", "HEAD:backtest").returncode == 0:
            return
        time.sleep(5 + 5 * i)


def num(s):
    s = re.sub(r"<[^>]+>|&nbsp;|,|\s", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def rev():
    rows, log = [], []
    y, m = 2023, 6
    while (y, m) <= (2026, 9):
        for mk in ("sii", "otc"):
            for k in (0, 1):
                got = False
                for host in ("https://mopsov.twse.com.tw", "https://mops.twse.com.tw"):
                    url = f"{host}/nas/t21/{mk}/t21sc03_{y - 1911}_{m}_{k}.html"
                    try:
                        raw = fetch(url, retries=2, timeout=60)
                    except Exception as e:
                        log.append(f"{url} 失敗 {e!r}")
                        continue
                    html = raw.decode("cp950", errors="replace")
                    n0 = len(rows)
                    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
                        td = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)
                        if len(td) < 10:
                            continue
                        code = re.sub(r"<[^>]+>|\s", "", td[0])
                        if not re.fullmatch(r"\d{4}", code):
                            continue
                        rows.append([f"{y}-{m:02d}", "上市" if mk == "sii" else "上櫃", code] + [num(x) for x in td[2:10]])
                    log.append(f"{url} {len(rows) - n0} 筆")
                    got = True
                    break
                if not got:
                    log.append(f"{y}-{m} {mk} {k} 抓不到")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    with open(f"{OUT}/revenue.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ym", "market", "code", "rev", "rev_prev", "rev_ly", "mom_pct", "yoy_pct", "cum", "cum_ly", "cum_yoy_pct"])
        w.writerows(rows)
    open(f"{OUT}/revenue_log.txt", "w").write("\n".join(log))
    save([f"{OUT}/revenue.csv", f"{OUT}/revenue_log.txt"], f"月營收 {len(rows)} 筆")


def sbl(part, parts):
    days = sorted(os.path.basename(p)[:10] for p in glob.glob("bt/raw/*.json.gz"))
    days = [d for d in days if d >= "2024-09-20"][part - 1::parts]
    out, meta = {}, None
    path = f"{OUT}/sbl_part{part}.json.gz"
    for i, d in enumerate(days):
        url = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={d.replace('-', '')}&response=json"
        try:
            j = get_json(url)
        except Exception as e:
            out[d] = {"_err": repr(e)}
            continue
        data = (j or {}).get("data") or []
        if meta is None and data:
            meta = True  # 欄位說明已經存過（第 2 份），其他份不再寫同一個檔，避免推送衝突
        day = {}
        for r in data:
            code = str(r[0]).strip()
            if re.fullmatch(r"\d{4}", code) and len(r) >= 13:
                day[code] = [num(str(r[9])), num(str(r[10])), num(str(r[12]))]  # 借券當日賣出、當日還券、當日餘額（股）
        out[d] = day
        if (i + 1) % 40 == 0:
            with gzip.open(path, "wt") as fh:
                json.dump(out, fh, separators=(",", ":"))
            save([path], f"借券 {part} {i + 1}")
    with gzip.open(path, "wt") as fh:
        json.dump(out, fh, separators=(",", ":"))
    save([path], f"借券 {part} 完成")


if __name__ == "__main__":
    if sys.argv[1] == "rev":
        rev()
    else:
        sbl(int(sys.argv[2]), int(sys.argv[3]))
