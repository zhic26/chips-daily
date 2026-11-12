"""存下原始回應當測試樣本（網站「國際盤勢」要改三件事，2026-11-12）：
1. 中央銀行每天公布的新臺幣對美元銀行間收盤匯率（要換掉 Yahoo 的國際報價），順便確認 GitHub 的機器連不連得到、憑證過不過
2. Yahoo 期貨、美元指數、新台幣的走勢圖回應（確認「一天」怎麼切）
3. 美國勞工統計局的 CPI 數列（季調、未季調；2025 年 10 月停擺沒資料，要改成顯示月增）
"""
import json
import os
import ssl
import subprocess
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "application/json, text/plain, text/html, */*", "Accept-Language": "zh-TW,zh;q=0.9"}
OUT = "bt/probe/macro3"
os.makedirs(OUT, exist_ok=True)
log = []


def get(url, data=None, headers=None, relaxed=False):
    ctx = None
    if relaxed:
        ctx = ssl.create_default_context()
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    req = urllib.request.Request(url, data=data, headers=dict(UA, **(headers or {})))
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        return r.read(), dict(r.headers)


def save(name, url, **kw):
    for relaxed in (False, True):
        for i in range(2):
            try:
                raw, hdr = get(url, relaxed=relaxed, **kw)
                open(os.path.join(OUT, name), "wb").write(raw)
                log.append(f"{name}: {len(raw)} bytes, relaxed={relaxed}, content-type={hdr.get('Content-Type')}")
                print(log[-1], flush=True)
                return
            except Exception as e:  # noqa: BLE001
                log.append(f"{name}: ERROR relaxed={relaxed} try={i + 1} {e!r}")
                print(log[-1], flush=True)
                time.sleep(8)


save("cbc_60.html", "https://www.cbc.gov.tw/tw/lp-645-1-1-60.html")
time.sleep(3)
save("cbc_default.html", "https://www.cbc.gov.tw/tw/lp-645-1.html")
time.sleep(3)
save("cbc_p2_60.html", "https://www.cbc.gov.tw/tw/lp-645-1-2-60.html")
for sym, name in (("CL%3DF", "CL_F"), ("GC%3DF", "GC_F"), ("DX-Y.NYB", "DXY"), ("TWD%3DX", "TWD_X"), ("%5ETNX", "TNX")):
    time.sleep(2)
    save(f"yahoo_{name}.json", f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1mo&interval=1d")
time.sleep(2)
save("bls_cpi.json", "https://api.bls.gov/publicAPI/v1/timeseries/data/",
     data=json.dumps({"seriesid": ["CUUR0000SA0", "CUUR0000SA0L1E", "CUSR0000SA0", "CUSR0000SA0L1E"],
                      "startyear": "2024", "endyear": "2026"}).encode(), headers={"Content-Type": "application/json"})
log.append("fetched at " + time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
open(os.path.join(OUT, "log.txt"), "w", encoding="utf-8").write("\n".join(log) + "\n")
subprocess.run(["git", "add", OUT])
subprocess.run(["git", "commit", "-qm", "國際盤勢三件修正的原始回應樣本"])
for i in range(10):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0:
        break
    time.sleep(5 + 5 * i)
