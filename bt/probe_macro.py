"""存下 Yahoo 走勢圖 API 與 Fed 會議日程的原始回應，當網站「國際盤勢」的測試樣本。"""
import json, os, subprocess, time, urllib.parse, urllib.request
OUT = "bt/probe_macro"; os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
        return r.read()
st = {}
for s in ["^SOX", "^IXIC", "^GSPC", "TSM", "^VIX", "^TNX", "DX-Y.NYB", "TWD=X", "CL=F", "GC=F"]:
    try:
        b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s)}?range=6mo&interval=1d")
        open(f"{OUT}/{s.replace('^', '').replace('=', '_')}.json", "wb").write(b); st[s] = len(b)
    except Exception as e:
        st[s] = repr(e)[:100]
    time.sleep(1)
for name, u in {"fomc": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"}.items():
    try:
        b = get(u); open(f"{OUT}/{name}.html", "wb").write(b); st[name] = len(b)
    except Exception as e:
        st[name] = repr(e)[:100]
json.dump(st, open(f"{OUT}/_status.json", "w"), indent=1)
subprocess.run(["git", "add", OUT]); subprocess.run(["git", "commit", "-qm", "macro fixtures"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0: break
    time.sleep(5)
