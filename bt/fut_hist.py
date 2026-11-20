"""期交所三大法人「區分各期貨契約」的歷史：2014/1 起每個月下載一次臺股期貨、小型臺指、微型臺指的三大法人交易與未平倉。
起因：使用者 2026-11-20 問外資台指期淨空單 9 萬多口在歷史上算不算多（網站只有 2026/7 以後的資料）。
存成 bt/fut_hist/YYYY-MM.csv（轉成 UTF-8、原本的欄位不動），每個月的結果記在 bt/fut_hist/_status.json。
先試一次查全部商品；期交所不接受的話，改成臺股期貨、小型臺指、微型臺指分開查再合起來。"""
import datetime as dt
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

OUT = "bt/fut_hist"
URL = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
os.makedirs(OUT, exist_ok=True)


def post(data):
    body = urllib.parse.urlencode(data).encode()
    err = None
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL, data=body, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5 * (k + 1))
    raise err


def dec(b):
    for enc in ("utf-8-sig", "cp950", "big5"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("cp950", errors="replace")


def is_csv(t):
    return "<html" not in t[:500].lower() and "商品名稱" in t[:500]


def months(start, end):
    a = start
    while a <= end:
        nxt = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield a, min(nxt - dt.timedelta(days=1), end)
        a = nxt


today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
st = {}
mode_all = None
for a, b in months(dt.date(2014, 1, 1), today):
    key = f"{a:%Y-%m}"
    q = {"queryStartDate": f"{a:%Y/%m/%d}", "queryEndDate": f"{b:%Y/%m/%d}"}
    try:
        texts = []
        if mode_all is not False:
            t = dec(post(dict(q, commodityId="")))
            if is_csv(t) and "臺股期貨" in t:
                texts, mode_all = [t], True
            elif mode_all is None:
                mode_all = False
            time.sleep(2)
        if not texts:
            for cid in ("TXF", "MXF", "TMF"):
                t = dec(post(dict(q, commodityId=cid)))
                if is_csv(t):
                    texts.append(t)
                time.sleep(2)
        if not texts:
            st[key] = "查無資料或不是 CSV"
            continue
        lines = texts[0].strip().splitlines()
        for t in texts[1:]:
            lines += t.strip().splitlines()[1:]
        open(f"{OUT}/{key}.csv", "w", encoding="utf-8").write("\n".join(lines) + "\n")
        days = sorted({ln.split(",")[0] for ln in lines[1:] if ln[:2] == "20"})
        st[key] = f"ok {len(lines) - 1} 列，{len(days)} 天 {days[0] if days else ''}～{days[-1] if days else ''}，{'全部商品一次查' if mode_all else '分開查'}"
    except Exception as e:  # noqa: BLE001
        st[key] = repr(e)[:200]
    print(key, st[key], flush=True)
json.dump(st, open(f"{OUT}/_status.json", "w"), ensure_ascii=False, indent=1)
subprocess.run(["git", "add", OUT])
subprocess.run(["git", "commit", "-qm", "期交所三大法人期貨歷史（2014 起）"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
        break
    time.sleep(5)
