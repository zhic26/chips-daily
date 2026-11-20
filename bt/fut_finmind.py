"""期交所網站只提供近三年的三大法人期貨資料（bt/fut_hist 只抓到 2023/12 起，更早要書面申請）。
改試 FinMind 的公開 API（TaiwanFuturesInstitutionalInvestors，非官方、轉載期交所資料），每年一段下載臺股期貨（TX）、小型臺指（MTX）。
存成 bt/fut_finmind/<代號>_<年>.json，每段結果記在 _status.json；之後跟 bt/fut_hist 重疊的期間對帳。"""
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

OUT = "bt/fut_finmind"
API = "https://api.finmindtrade.com/api/v4/data"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
os.makedirs(OUT, exist_ok=True)
st = {}
for did in ("TX", "MTX"):
    for y in range(2010, 2027):
        q = {"dataset": "TaiwanFuturesInstitutionalInvestors", "data_id": did, "start_date": f"{y}-01-01", "end_date": f"{y}-12-31"}
        key = f"{did}_{y}"
        try:
            with urllib.request.urlopen(urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers=UA), timeout=90) as r:
                j = json.loads(r.read().decode("utf-8"))
            data = j.get("data") or []
            if data:
                json.dump(j, open(f"{OUT}/{key}.json", "w"), ensure_ascii=False)
            ds = sorted({d.get("date") for d in data})
            st[key] = f"msg={j.get('msg')} status={j.get('status')} 筆數={len(data)} {ds[0] if ds else ''}～{ds[-1] if ds else ''}"
        except Exception as e:  # noqa: BLE001
            st[key] = repr(e)[:200]
        print(key, st[key], flush=True)
        time.sleep(3)
json.dump(st, open(f"{OUT}/_status.json", "w"), ensure_ascii=False, indent=1)
subprocess.run(["git", "add", OUT])
subprocess.run(["git", "commit", "-qm", "FinMind 三大法人期貨歷史（2010 起）"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
        break
    time.sleep(5)
