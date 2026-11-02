"""櫃買三大法人舊日期的回應格式：哪一天開始抓得到、欄位長怎樣。結果寫進 bt/probe11.txt。"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from chips.net import get_json  # noqa: E402

TPEX = "https://www.tpex.org.tw/www/zh-tw"
out = []
for ds in ["2014/01/06", "2015/06/01", "2016/06/15", "2017/09/12", "2017/12/15", "2017/12/18", "2018/01/02",
           "2018/01/15", "2018/03/15", "2018/06/15"]:
    for sect in ("EW", "AL"):
        url = f"{TPEX}/insti/dailyTrade?type=Daily&sect={sect}&date={ds}&response=json"
        try:
            j = get_json(url, retries=2)
        except Exception as e:  # noqa: BLE001
            out.append(f"{ds} {sect} 失敗 {e!r}"[:300])
            continue
        keys = list(j.keys()) if isinstance(j, dict) else type(j).__name__
        line = [f"{ds} {sect} keys={keys} stat={j.get('stat') if isinstance(j, dict) else ''} total={j.get('totalCount') if isinstance(j, dict) else ''}"]
        for k, t in enumerate((j.get("tables") or []) if isinstance(j, dict) else []):
            line.append(f"   table{k} keys={list(t.keys())} title={t.get('title')} fields={t.get('fields')}")
            data = t.get("data") or t.get("aaData") or []
            line.append(f"   筆數={len(data)} 欄數={len(data[0]) if data else 0} 第一列={json.dumps(data[0], ensure_ascii=False) if data else None}")
        if isinstance(j, dict) and "aaData" in j:
            line.append(f"   aaData 筆數={len(j['aaData'])} 第一列={json.dumps(j['aaData'][0], ensure_ascii=False) if j['aaData'] else None}")
        out.append("\n".join(line))
        print(out[-1][:500], flush=True)
open("bt/probe11.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
subprocess.run(["git", "add", "bt/probe11.txt"])
subprocess.run(["git", "commit", "-qm", "櫃買法人舊格式探測結果"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
        break
