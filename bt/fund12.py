"""12 年回測用（2026-11-09，使用者要測本益比、季報、借券）：每 5 個交易日抓一次，季報每季抓一次。
用法：
  python bt/fund12.py val  twse|tpex 起日 迄日  → bt/val/<市場>/YYYY-MM-DD.json.gz：{代號: [本益比, 股價淨值比, 殖利率%]}（同 valuation.py）
  python bt/fund12.py sbl  twse|tpex 起日 迄日  → bt/sbl/<市場>/YYYY-MM-DD.json.gz：{"url": 用的網址, "fields": 欄位, "rows": {代號: [各欄數字]}}
  python bt/fund12.py mops twse|tpex            → bt/mops/<市場>/<民國年>Q<季>.html.gz：公開資訊觀測站綜合損益表彙總（原始內容，事後解析）
取樣日是 bt/raw 全部交易日裡「第 0、5、10…個」，所有工作對齊同一組日子。任何一天失敗都不中斷，每 40 筆存回 backtest 分支。"""
import datetime as dt
import glob
import gzip
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
MODE, MK = sys.argv[1], sys.argv[2]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
GAP = {"mops": 6.0}.get(MODE, 3.6 if MK == "twse" else 2.6)
_last = [0.0]


def request(url, data=None, headers=None, tries=4):
    for i in range(tries):
        wait = _last[0] + GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            print("  重試", i + 1, url[-70:], repr(e)[:100], flush=True)
            time.sleep(8 * (i + 1))
    return None


def get_json(url):
    t = request(url)
    if t is None:
        return None
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        print("  不是 JSON：", t[:120].replace("\n", " "), flush=True)
        return None


def num(s):
    s = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def clean(x):
    return re.sub(r"<[^>]+>|\s", "", str(x))


def tables(j):
    """各種格式的 JSON → [(欄位, 資料列)]。"""
    if not isinstance(j, dict):
        return []
    out = []
    if j.get("data"):
        out.append((j.get("fields"), j.get("data")))
    for t in j.get("tables") or []:
        if isinstance(t, dict) and t.get("data"):
            out.append((t.get("fields"), t.get("data")))
    if j.get("aaData"):
        out.append((None, j["aaData"]))
    return out


# ---------- 估值（同 valuation.py） ----------

def col(fields, *names):
    f = [clean(x) for x in fields]
    for n in names:
        for i, x in enumerate(f):
            if x.startswith(n):
                return i
    return None


def parse_val(j):
    for fields, rows in tables(j):
        if not rows or len(rows) < 300:
            continue
        if fields:
            c, pe, pb, y = col(fields, "證券代號", "股票代號", "代號"), col(fields, "本益比"), col(fields, "股價淨值比"), col(fields, "殖利率")
        else:  # 舊版櫃買沒有欄位名稱：代號、名稱、本益比、每股股利、股利年度、殖利率、股價淨值比
            c, pe, y, pb = 0, 2, 5, 6
        if None in (c, pe, pb, y):
            print("  欄位對不上：", fields, flush=True)
            return None
        out = {}
        for r in rows:
            code = str(r[c]).strip()
            if re.fullmatch(r"[1-9]\d{3}", code):
                out[code] = [num(r[pe]), num(r[pb]), num(r[y])]
        return out
    return None


def val_urls(d):
    roc = f"{d.year - 1911}/{d:%m/%d}"
    if MK == "twse":
        return [f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={d:%Y%m%d}&selectType=ALL&response=json",
                f"https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=json&date={d:%Y%m%d}&selectType=ALL"]
    return [f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date={d:%Y/%m/%d}&response=json",
            f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peratio?date={d:%Y/%m/%d}&response=json",
            f"https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php?l=zh-tw&o=json&d={roc}"]


# ---------- 借券賣出 ----------

def parse_sbl(j, url):
    for fields, rows in tables(j):
        if not rows or len(rows) < 300:
            continue
        f = [clean(x) for x in fields] if fields else None
        out = {}
        for r in rows:
            code = clean(r[0])
            if re.fullmatch(r"[1-9]\d{3}", code):
                out[code] = [num(x) for x in r[2:]]
        if len(out) >= 200:
            return {"url": url, "fields": f, "rows": out}
    return None


def sbl_urls(d):
    roc = f"{d.year - 1911}/{d:%m/%d}"
    if MK == "twse":
        return [f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={d:%Y%m%d}&response=json",
                f"https://www.twse.com.tw/exchangeReport/TWT93U?response=json&date={d:%Y%m%d}"]
    return [f"https://www.tpex.org.tw/www/zh-tw/margin/sbl?date={d:%Y/%m/%d}&response=json",
            f"https://www.tpex.org.tw/www/zh-tw/margin/sblBalance?date={d:%Y/%m/%d}&response=json",
            f"https://www.tpex.org.tw/web/stock/margin_trading/margin_sbl/margin_sbl_result.php?l=zh-tw&o=json&d={roc}"]


# ---------- 存回分支 ----------

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


def commit(out, tag):
    git("add", out)
    if git("commit", "-qm", f"回測資料 {MODE} {MK} {tag}").returncode != 0:
        return
    for i in range(12):
        git("pull", "-q", "--rebase", "origin", "backtest")
        if git("push", "-q", "origin", "HEAD:backtest").returncode == 0:
            print("已存回", tag, flush=True)
            return
        time.sleep(5 + 7 * i)
    print("存回失敗", tag, flush=True)


def save(path, obj, raw=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(obj) if raw else json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def run_daily(parse, urls, out):
    start, end = (dt.date.fromisoformat(x) for x in sys.argv[3:5])
    days = sorted(dt.date.fromisoformat(os.path.basename(p)[:10]) for p in glob.glob("bt/raw/*.json.gz"))
    pick = [d for i, d in enumerate(days) if i % 5 == 0 and start <= d <= end]
    todo = [d for d in pick if not os.path.exists(f"{out}/{d}.json.gz")]
    print(MODE, MK, f"取樣 {len(pick)} 天，要下載 {len(todo)} 天", flush=True)
    if not todo:
        return

    def try_day(d, k):
        u = urls(d)[k]
        j = get_json(u)
        return parse(j, u) if parse is parse_sbl else parse(j)

    # 找可用的網址：先用第一天試，不行再往後找有資料的日子
    k_ok, first = None, 0
    while first < len(todo) and k_ok is None:
        for k in range(len(urls(todo[first]))):
            got = try_day(todo[first], k)
            print("  試網址", k, todo[first], "→", (len(got["rows"]) if isinstance(got, dict) and "rows" in got else len(got)) if got else got, flush=True)
            if got:
                k_ok = k
                save(f"{out}/{todo[first]}.json.gz", got)
                break
        if k_ok is None:
            first += 25  # 這段可能還沒有這種資料，往後跳約半年
    if k_ok is None:
        print("所有網址、所有日子都沒有資料，結束", flush=True)
        return
    if first:
        print(f"  前 {first} 個取樣日沒有資料（{todo[0]}～{todo[first - 1]}），從 {todo[first]} 開始", flush=True)
    n = bad = 0
    for d in todo[first + 1:]:
        got = try_day(d, k_ok)
        if not got:
            bad += 1
            print("  沒有資料", d, flush=True)
            continue
        save(f"{out}/{d}.json.gz", got)
        n += 1
        if n % 40 == 0:
            commit(out, str(d))
    commit(out, "完成")
    print("完成", n + 1, "天，失敗", bad, "天", flush=True)


def run_mops():
    out = f"bt/mops/{MK}"
    typek = "sii" if MK == "twse" else "otc"
    qs = [(y, s) for y in range(102, 116) for s in (1, 2, 3, 4) if (y, s) <= (115, 2)]
    tries = [
        ("舊版", lambda y, s: ("https://mops.twse.com.tw/mops/web/ajax_t163sb04",
                              urllib.parse.urlencode({"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
                                                      "TYPEK": typek, "year": y, "season": f"{s:02d}"}).encode(),
                              {"Content-Type": "application/x-www-form-urlencoded", "Referer": "https://mops.twse.com.tw/mops/web/t163sb04"})),
        ("新版", lambda y, s: ("https://mops.twse.com.tw/mops/api/t163sb04",
                              json.dumps({"year": str(y), "season": str(s), "TYPEK": typek}).encode(),
                              {"Content-Type": "application/json", "Referer": "https://mops.twse.com.tw/mops/"})),
    ]
    ok = None
    y0, s0 = qs[-4]
    for name, mk in tries:
        u, data, h = mk(y0, s0)
        t = request(u, data, h, tries=2)
        good = bool(t) and len(t) > 20000 and ("毛利" in t or "每股盈餘" in t)
        print("  試", name, f"{y0}Q{s0}", "→", len(t) if t else t, "OK" if good else (t or "")[:200].replace("\n", " "), flush=True)
        if good:
            ok = mk
            save(f"{out}/{y0}Q{s0}.html.gz", t, raw=True)
            break
    if not ok:
        print("公開資訊觀測站兩種網址都抓不到，結束", flush=True)
        return
    n = 0
    for y, s in qs:
        p = f"{out}/{y}Q{s}.html.gz"
        if os.path.exists(p):
            continue
        u, data, h = ok(y, s)
        t = request(u, data, h, tries=3)
        if t and len(t) > 20000:
            save(p, t, raw=True)
            n += 1
        else:
            print("  沒抓到", y, s, (t or "")[:120].replace("\n", " "), flush=True)
        if n and n % 15 == 0:
            commit(out, f"{y}Q{s}")
    commit(out, "完成")
    print("完成", n, "季", flush=True)


if MODE == "val":
    run_daily(parse_val, val_urls, f"bt/val/{MK}")
elif MODE == "sbl":
    run_daily(parse_sbl, sbl_urls, f"bt/sbl/{MK}")
elif MODE == "mops":
    run_mops()
else:
    sys.exit("用法見檔案開頭")
