"""探測：注意／處置股資料來源，並把各資料來源的回應裁短存成測試用樣本。"""
import json, os, re, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from chips.net import fetch
OUT = "bt/probe"; os.makedirs(OUT, exist_ok=True)
T, TP = "https://www.twse.com.tw/rwd/zh", "https://www.tpex.org.tw/www/zh-tw"
urls = {
 "holiday": f"{T}/holidaySchedule/holidaySchedule?date=20260101&response=json",
 "tpex_attention_range": f"{TP}/bulletin/attention?date=2026/10/15&response=json",
 "twse_notice_rwd": f"{T}/announcement/notice?querytype=1&stockNo=&selectType=&startDate=20261022&endDate=20261022&response=json",
 "twse_punish_rwd": f"{T}/announcement/punish?querytype=3&stockNo=&selectType=&proceType=&remarkType=&startDate=20261001&endDate=20261022&response=json",
 "twse_notice_open": "https://openapi.twse.com.tw/v1/announcement/notice",
 "twse_punish_open": "https://openapi.twse.com.tw/v1/announcement/punish",
 "tpex_warn_open": "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information",
 "tpex_disp_open": "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information",
 "tpex_attention_www": f"{TP}/bulletin/attention?date=2026/10/22&response=json",
 "tpex_disposal_www": f"{TP}/bulletin/disposal?startDate=2026/10/01&endDate=2026/10/22&response=json",
 "tpex_warning_www": f"{TP}/bulletin/warning?date=2026/10/22&response=json",
 "fx_T86": f"{T}/fund/T86?date=20261022&selectType=ALLBUT0999&response=json",
 "fx_MI_INDEX": f"{T}/afterTrading/MI_INDEX?date=20261022&type=ALLBUT0999&response=json",
 "fx_MI_MARGN": f"{T}/marginTrading/MI_MARGN?date=20261022&selectType=ALL&response=json",
 "fx_tpex_insti": f"{TP}/insti/dailyTrade?type=Daily&sect=EW&date=2026/10/22&response=json",
 "fx_tpex_otc": f"{TP}/afterTrading/otc?date=2026/10/22&type=EW&response=json",
 "fx_tpex_margin": f"{TP}/margin/balance?date=2026/10/22&response=json",
}
CS = re.compile(r"[1-9]\d{3}")
def trim(o):
    if isinstance(o, list):
        if o and isinstance(o[0], list):  # 資料列：留前 5 列＋前 20 檔普通股
            keep = o[:5] + [r for r in o[5:] if any(CS.fullmatch(str(x).strip()) for x in r[:3])][:20]
            return keep
        return [trim(x) for x in o[:25]]
    if isinstance(o, dict):
        return {k: trim(v) for k, v in o.items()}
    return o
summary = {}
for k, u in urls.items():
    try:
        raw = fetch(u, retries=2, timeout=60)
        txt = raw.decode("utf-8", errors="replace")
        try:
            j = json.loads(txt)
            info = {"ok": True, "type": type(j).__name__, "len": len(j) if isinstance(j, list) else None,
                    "keys": list(j[0].keys()) if isinstance(j, list) and j and isinstance(j[0], dict) else (list(j.keys()) if isinstance(j, dict) else None)}
            if isinstance(j, dict):
                for kk in ("fields", "title", "stat", "date"):
                    if kk in j: info[kk] = j[kk]
                if "tables" in j and j["tables"]:
                    info["tables"] = [{"title": t.get("title"), "fields": t.get("fields"), "n": len(t.get("data") or [])} for t in j["tables"][:3]]
                if "data" in j: info["n"] = len(j.get("data") or []); info["row0"] = (j.get("data") or [None])[0]
            elif isinstance(j, list) and j: info["row0"] = j[0]
            json.dump(trim(j), open(f"{OUT}/{k}.json", "w"), ensure_ascii=False)
        except ValueError:
            info = {"ok": False, "head": txt[:200]}
    except Exception as e:
        info = {"ok": False, "err": repr(e)[:200]}
    summary[k] = info
json.dump(summary, open(f"{OUT}/_summary.json", "w"), ensure_ascii=False, indent=1)
subprocess.run(["git", "add", OUT]); subprocess.run(["git", "commit", "-qm", "probe"])
for i in range(8):
    subprocess.run(["git", "pull", "-q", "--rebase", "origin", "backtest"])
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:backtest"]).returncode == 0: break
