"""探測：期交所三大法人台指期未平倉、櫃買指數月表。存原始回應當測試樣本。"""
import json, os, subprocess, time, urllib.parse, urllib.request
OUT = "bt/probe_fut"; os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def get(u, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    with urllib.request.urlopen(urllib.request.Request(u, data=body, headers=UA), timeout=60) as r:
        return r.read(), r.headers.get("Content-Type")
st = {}
reqs = {
  "taifex_csv_range.csv": ("https://www.taifex.com.tw/cht/3/futContractsDateDown", {"queryStartDate": "2026/09/21", "queryEndDate": "2026/10/22", "commodityId": "TXF"}),
  "taifex_html.html": ("https://www.taifex.com.tw/cht/3/futContractsDate?queryDate=2026%2F10%2F22&commodityId=TXF", None),
  "taifex_open.json": ("https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate", None),
  "tpex_inx_2026_09.json": ("https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date=2026/09/15&response=json", None),
}
for name, (u, data) in reqs.items():
    try:
        b, ct = get(u, data); open(f"{OUT}/{name}", "wb").write(b)
        st[name] = f"ok {len(b)}B {ct} head={b[:120]!r}"
    except Exception as e:
        st[name] = repr(e)[:150]
    time.sleep(2)
json.dump(st, open(f"{OUT}/_status.json", "w"), ensure_ascii=False, indent=1)
subprocess.run(["git", "add", OUT]); subprocess.run(["git", "commit", "-qm", "probe fut"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0: break
    time.sleep(5)
