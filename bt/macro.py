"""抓美國總經與市場資料（回測國際行情能不能幫名單），順便測試哪些來源在 GitHub Actions 抓得到。"""
import json, os, subprocess, sys, urllib.parse, urllib.request
OUT = "bt/macro"; os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def get(u):
    req = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()
status = {}
for sid in ["VIXCLS", "NASDAQCOM", "SP500", "DGS10", "DGS2", "DTWEXBGS", "DEXTAUS", "BAMLH0A0HYM2", "DCOILWTICO"]:
    u = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2024-01-01"
    try:
        b = get(u); open(f"{OUT}/fred_{sid}.csv", "wb").write(b); status[sid] = f"ok {len(b)}B"
    except Exception as e:
        status[sid] = repr(e)[:120]
for sym in ["^SOX", "TSM", "2330.TW", "^TWII", "^IXIC"]:
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?period1=1704067200&period2=1793000000&interval=1d"
    try:
        j = json.loads(get(u)); r = j["chart"]["result"][0]
        rows = list(zip(r["timestamp"], r["indicators"]["quote"][0]["close"], r["indicators"]["quote"][0]["open"]))
        json.dump(rows, open(f"{OUT}/yahoo_{sym.replace('^', '')}.json", "w")); status[sym] = f"ok {len(rows)} rows"
    except Exception as e:
        status[sym] = repr(e)[:120]
for name, u in {"stooq_sox": "https://stooq.com/q/d/l/?s=^sox&i=d",
                "nasdaq_sox": "https://api.nasdaq.com/api/quote/SOX/historical?assetclass=index&fromdate=2026-09-01&limit=10",
                "fed_fomc": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                "bls_cpi": "https://www.bls.gov/schedule/news_release/cpi.htm",
                "cbc_fx": "https://www.cbc.gov.tw/tw/lp-645-1.html"}.items():
    try:
        b = get(u); status[name] = f"ok {len(b)}B head={b[:60]!r}"
    except Exception as e:
        status[name] = repr(e)[:120]
json.dump(status, open(f"{OUT}/_status.json", "w"), ensure_ascii=False, indent=1)
subprocess.run(["git", "add", OUT]); subprocess.run(["git", "commit", "-qm", "macro data"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0: break
