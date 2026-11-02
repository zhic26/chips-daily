"""十年回測的補充資料：
  python bt/extra10.py twt49u   證交所除權息參考價（TWT49U），2013/12～2024/05 每月一個檔
  python bt/extra10.py rev      月營收（公開資訊觀測站彙總表），2013/01～2023/05，存成 bt/extra2/revenue_old.csv"""
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from chips.net import fetch, get_json  # noqa: E402


def save(paths, tag):
    subprocess.run(["git", "add", *paths])
    if subprocess.run(["git", "commit", "-qm", tag]).returncode != 0:
        return
    for i in range(10):
        subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
        if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
            print("已存回", tag, flush=True)
            return
    print("推送失敗", tag, flush=True)


def num(s):
    s = re.sub(r"<[^>]+>|&nbsp;|,|\s", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def twt49u():
    os.makedirs("bt/extra", exist_ok=True)
    d, done = dt.date(2013, 12, 1), []
    while d <= dt.date(2024, 5, 31):
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        path = f"bt/extra/twt49u_{d:%Y%m}.json"
        if not os.path.exists(path):
            url = (f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json"
                   f"&startDate={d:%Y%m%d}&endDate={nxt - dt.timedelta(days=1):%Y%m%d}")
            try:
                j = get_json(url)
                json.dump(j, open(path, "w"), ensure_ascii=False)
                done.append(path)
                print(d, "筆數", len(j.get("data") or []) if isinstance(j, dict) else 0, flush=True)
            except Exception as e:  # noqa: BLE001
                print(d, "失敗", e, flush=True)
        if len(done) >= 24:
            save(done, f"除權息參考價 到 {d:%Y-%m}")
            done = []
        d = nxt
    save(done or ["bt/extra"], "除權息參考價 2013/12～2024/05 完成")


def rev():
    out = "bt/extra2"
    os.makedirs(out, exist_ok=True)
    rows, log = [], []
    y, m = 2013, 1
    while (y, m) <= (2023, 5):
        for mk in ("sii", "otc"):
            for k in (0, 1):
                got = False
                for host in ("https://mopsov.twse.com.tw", "https://mops.twse.com.tw"):
                    url = f"{host}/nas/t21/{mk}/t21sc03_{y - 1911}_{m}_{k}.html"
                    try:
                        raw = fetch(url, retries=2, timeout=60)
                    except Exception as e:  # noqa: BLE001
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
        print(y, m, len(rows), flush=True)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    with open(f"{out}/revenue_old.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ym", "market", "code", "rev", "rev_prev", "rev_ly", "mom_pct", "yoy_pct", "cum", "cum_ly", "cum_yoy_pct"])
        w.writerows(rows)
    open(f"{out}/revenue_old_log.txt", "w").write("\n".join(log))
    save([f"{out}/revenue_old.csv", f"{out}/revenue_old_log.txt"], f"舊月營收 {len(rows)} 筆")


if __name__ == "__main__":
    {"twt49u": twt49u, "rev": rev}[sys.argv[1]]()
