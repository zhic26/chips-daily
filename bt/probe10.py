"""十年回測前的探測：舊日期的每個來源抓不抓得到、格式對不對；舊月份的月營收抓不抓得到。
結果寫進 bt/probe10.txt 並存回 backtest 分支。"""
import datetime as dt
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from chips import daily as D  # noqa: E402
from chips import store  # noqa: E402
from chips.net import fetch  # noqa: E402

DATES = ["2013-06-14", "2014-01-06", "2014-06-17", "2015-06-01", "2016-06-15", "2017-09-12", "2018-10-11",
         "2019-08-14", "2020-03-19", "2021-05-12", "2022-06-15", "2023-03-15", "2024-06-28"]
out = []


def say(s):
    out.append(s)
    print(s, flush=True)


comp = (store.load_meta("companies") or {}).get("data", {})
for ds in DATES:
    d = dt.date.fromisoformat(ds)
    ex = D.blank(d)
    line = [ds]
    for src in D.SOURCES:
        try:
            ok = D._run(src, d, ex, comp)
            line.append(f"{src}={'OK' if ok else 'EMPTY'}")
        except Exception as e:  # noqa: BLE001
            line.append(f"{src}=ERR {type(e).__name__}: {str(e)[:150]}")
    say(" | ".join(line))
    say(f"   筆數 q={len(ex['q'])} inst={len(ex['inst'])} margin={len(ex['margin'])} dt={len(ex['dt'])} "
        f"指數={list(ex['indices'])[:4]} market={sorted(ex['market'])}")
    say(f"   2330 q={ex['q'].get('2330')} inst={ex['inst'].get('2330')} margin={ex['margin'].get('2330')} dt={ex['dt'].get('2330')}")
    say(f"   上櫃樣本 5347 q={ex['q'].get('5347')} inst={ex['inst'].get('5347')} 加權={ex['indices'].get('加權指數')} 櫃買={ex['indices'].get('櫃買指數')}")

for y, m in [(2012, 1), (2013, 1), (2016, 6), (2020, 3)]:
    for mk in ("sii", "otc"):
        for host in ("https://mopsov.twse.com.tw", "https://mops.twse.com.tw"):
            url = f"{host}/nas/t21/{mk}/t21sc03_{y - 1911}_{m}_0.html"
            try:
                raw = fetch(url, retries=2, timeout=60)
                html = raw.decode("cp950", errors="replace")
                say(f"月營收 {y}-{m:02d} {mk} {host}: {len(raw)} bytes, <tr {html.lower().count('<tr')} 個")
                break
            except Exception as e:  # noqa: BLE001
                say(f"月營收 {y}-{m:02d} {mk} {host}: 失敗 {e!r}"[:220])

open("bt/probe10.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
subprocess.run(["git", "add", "bt/probe10.txt"])
subprocess.run(["git", "commit", "-qm", "十年回測探測結果"])
for i in range(5):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
        break
