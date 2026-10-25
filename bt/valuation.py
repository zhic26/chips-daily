"""回測用：下載每個交易日的本益比、股價淨值比、殖利率（上市：證交所 BWIBBU_d；上櫃：櫃買中心）。
存成 bt/val/<market>/YYYY-MM-DD.json.gz：{代號: [本益比, 股價淨值比, 殖利率%]}（虧損公司本益比為 null）。
用法：python bt/valuation.py twse|tpex"""
import datetime as dt, glob, gzip, json, os, re, subprocess, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
MK = sys.argv[1]
OUT = f"bt/val/{MK}"
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
GAP = 3.6 if MK == "twse" else 2.6
_last = [0.0]


def get_json(url):
    for i in range(5):
        wait = _last[0] + GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            print("  重試", i + 1, url[-60:], repr(e)[:80], flush=True)
            time.sleep(10 * (i + 1))
    return None


def num(s):
    s = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def col(fields, *names):
    f = [re.sub(r"<[^>]+>|\s", "", str(x)) for x in fields]
    for n in names:
        for i, x in enumerate(f):
            if x.startswith(n):
                return i
    return None


def parse(j):
    """回傳 {代號: [pe, pb, yld]}；格式看不懂回傳 None。"""
    if not isinstance(j, dict):
        return None
    tabs = [(j.get("fields"), j.get("data"))] if j.get("data") else [(t.get("fields"), t.get("data")) for t in j.get("tables") or []]
    if j.get("aaData"):
        tabs.append((None, j["aaData"]))
    for fields, rows in tabs:
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


def url_for(d, k):
    if MK == "twse":
        return f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={d:%Y%m%d}&selectType=ALL&response=json"
    roc = f"{d.year - 1911}/{d:%m/%d}"
    return [f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date={d:%Y/%m/%d}&response=json",
            f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peratio?date={d:%Y/%m/%d}&response=json",
            f"https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php?l=zh-tw&o=json&d={roc}"][k]


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


def commit(tag):
    git("add", OUT)
    if git("commit", "-qm", f"估值資料 {MK} {tag}").returncode != 0:
        return
    for i in range(10):
        git("pull", "-q", "--rebase", "origin", "backtest")
        if git("push", "-q", "origin", "HEAD:backtest").returncode == 0:
            print("已存回", tag, flush=True)
            return
        time.sleep(5 + 7 * i)


days = sorted(dt.date.fromisoformat(os.path.basename(p)[:10]) for p in glob.glob("bt/raw/*.json.gz"))
todo = [d for d in days if not os.path.exists(f"{OUT}/{d}.json.gz")]
print(MK, "要下載", len(todo), "天", flush=True)
k = 0
if MK == "tpex" and todo:  # 找出可用的櫃買網址
    for k in range(3):
        got = parse(get_json(url_for(todo[-1], k)))
        print("  櫃買網址", k, "→", len(got) if got else got, flush=True)
        if got:
            break
    else:
        sys.exit("櫃買估值網址都不能用")
n = bad = 0
for d in todo:
    data = parse(get_json(url_for(d, k)))
    if not data:
        bad += 1
        print("  沒有資料", d, flush=True)
        continue
    with gzip.open(f"{OUT}/{d}.json.gz", "wt") as f:
        json.dump(data, f, separators=(",", ":"))
    n += 1
    if n % 80 == 0:
        commit(str(d))
commit("完成")
print("完成", n, "天，失敗", bad, "天", flush=True)
