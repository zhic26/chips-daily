"""國際盤勢：美國股市、利率、美元、新台幣與原物料最近一個交易日的收盤，加上重要事件日曆。

只放在網站上看大環境，不影響名單分數。回測裡，美股前一晚的漲跌在台股隔天開盤價就反映了
（費半當晚漲跌和台股隔天開盤跳空的相關係數 0.63，和開盤後到收盤只有 −0.14），名單又是隔天開盤買，
所以把美股放進分數不會讓名單更準。

資料：
- Yahoo Finance 的走勢圖介面（非官方，可能改版；抓不到時這一區顯示上次的數字並註明，名單照常更新）
- 美國聯準會網站的 FOMC 會議日程（每週重抓一次）
- 手動維護的 events.json：美國 CPI、非農就業、台灣央行理監事會（每年底補上隔年的日期）
"""
import datetime as dt
import json
import os
import re
import urllib.parse
from zoneinfo import ZoneInfo

from . import store
from .checks import DataError
from .net import FetchError, get_json, get_text

TPE = ZoneInfo("Asia/Taipei")

# key, Yahoo 代號, 名稱, 單位, 合理範圍（超出就當作資料有問題）
SYMBOLS = [
    ("sox", "^SOX", "費城半導體", "", (500, 60000)),
    ("ixic", "^IXIC", "那斯達克", "", (2000, 150000)),
    ("spx", "^GSPC", "S&P 500", "", (500, 40000)),
    ("tsm", "TSM", "台積電 ADR", "美元", (10, 5000)),
    ("vix", "^VIX", "VIX 恐慌指數", "", (5, 100)),
    ("tnx", "^TNX", "美國 10 年期公債殖利率", "%", (0.1, 20)),
    ("dxy", "DX-Y.NYB", "美元指數", "", (60, 160)),
    ("twd", "TWD=X", "新台幣匯率", "元", (20, 45)),
    ("wti", "CL=F", "西德州原油", "美元", (-50, 400)),
    ("gold", "GC=F", "黃金", "美元", (300, 20000)),
]
NAMES = {k: n for k, _, n, _, _ in SYMBOLS}
SPARK = 60
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=6mo&interval=1d"
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
EVENTS = os.path.join(store.ROOT, "events.json")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
ADR_RATIO = 5  # 1 股台積電 ADR = 5 股台股


# ---------------- 解析 ----------------

def parse_chart(j, now_ts):
    """Yahoo 走勢圖回應 → [(交易所當地日期, 收盤)]，舊到新。
    去掉週末的零星報價、還沒收盤的那一根，同一天只留一筆。"""
    try:
        r = j["chart"]["result"][0]
        ts = r.get("timestamp") or []
        closes = r["indicators"]["quote"][0]["close"]
        meta = r["meta"]
    except (KeyError, IndexError, TypeError) as e:
        raise DataError(f"Yahoo 走勢圖的回應格式變了（{e!r}）") from e
    try:
        tz = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
    except Exception:  # noqa: BLE001  時區名稱看不懂就用 UTC
        tz = dt.timezone.utc
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    bars = []
    for t, c in zip(ts, closes):
        if c is None or t > now_ts:
            continue
        d = dt.datetime.fromtimestamp(t, tz).date()
        if d.weekday() < 5:
            bars.append((t, d, float(c)))
    if bars and reg.get("start") and reg.get("end") and reg["start"] <= now_ts < reg["end"] \
            and bars[-1][0] >= reg["start"] - 12 * 3600:
        bars.pop()  # 正在交易、還沒收盤
    out = {}
    for _, d, c in bars:
        out[d.isoformat()] = c
    return sorted(out.items())


def stats(series):
    """最新收盤、1／5／20 日漲跌（%）、相對 50 日均線（%）、1／20 日變動（點數），以及走勢小圖。"""
    v = [c for _, c in series]
    last = v[-1]

    def chg(k):
        return round((last / v[-1 - k] - 1) * 100, 2) if len(v) > k and v[-1 - k] else None

    def diff(k):
        return round(last - v[-1 - k], 4) if len(v) > k else None

    ma50 = sum(v[-50:]) / 50 if len(v) >= 50 else None
    return {"date": series[-1][0], "last": round(last, 4), "chg1": chg(1), "chg5": chg(5), "chg20": chg(20),
            "d1": diff(1), "d20": diff(20), "avg20": round(sum(v[-20:]) / len(v[-20:]), 4),
            "ma50": round((last / ma50 - 1) * 100, 2) if ma50 else None,
            "spark": [round(x, 4) for x in v[-SPARK:]], "from": series[-SPARK:][0][0]}


def adr_premium(tsm, twd, tw_close):
    """台積電 ADR 溢價（%）：ADR 收盤 ÷（台股收盤 × 5 ÷ 匯率）− 1。
    同一個日曆日的 ADR 與台股收盤；匯率用當天或之前最近一天。回傳 [(日期, 溢價)]。"""
    if not tsm or not twd or not tw_close:
        return []
    t, fx = dict(tsm), sorted(twd)
    out = []
    for d, c in sorted(tw_close.items()):
        rate = [r for x, r in fx if x <= d]
        if d in t and c and rate:
            out.append((d, round((t[d] / (c * ADR_RATIO / rate[-1]) - 1) * 100, 2)))
    return out[-SPARK:]


def parse_fomc(html):
    """聯準會會議日程頁 → [{"date": 決策日, "sep": 是否公布經濟預測}]。只收定期會議（不含 notation vote）。"""
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r"(\d{4}) FOMC Meetings", html)]
    out = []
    for pos, year in heads:
        end = min([p for p, _ in heads if p > pos], default=len(html))
        month = None
        for kind, txt in re.findall(r'class="[^"]*fomc-meeting__(month|date)[^"]*"[^>]*>(.*?)</div>', html[pos:end], flags=re.S):
            txt = re.sub(r"<[^>]+>", "", txt).strip()
            if kind == "month":
                month = txt
                continue
            m = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?(\*?)", txt)
            if not month or not m:
                continue  # 例如「22 (notation vote)」、臨時會議
            first, last = int(m.group(1)), int(m.group(2) or m.group(1))
            names = month.lower().split("/")
            name = names[-1] if last < first and len(names) > 1 else names[0]
            mi = MONTHS.get(name[:3])
            if not mi:
                continue
            try:
                out.append({"date": dt.date(year, mi, last).isoformat(), "sep": m.group(3) == "*"})
            except ValueError:
                continue
    if not out:
        raise DataError("聯準會會議日程頁看不懂，網站可能改版")
    return sorted({x["date"]: x for x in out}.values(), key=lambda x: x["date"])


def upcoming(now, fomc, manual, days=40, limit=6):
    """接下來 days 天內的事件，換算成台北時間。"""
    ev = [{"date": m["date"], "time": "14:00", "tz": "America/New_York", "kind": "fomc_sep" if m.get("sep") else "fomc",
           "name": "Fed 利率決策"} for m in fomc]
    out = []
    for e in ev + list(manual):
        d = dt.date.fromisoformat(e["date"])
        if e.get("time"):
            hh, mm = (int(x) for x in e["time"].split(":"))
            at = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(e.get("tz") or "Asia/Taipei")).astimezone(TPE)
            show = at
        else:
            at = dt.datetime(d.year, d.month, d.day, 23, 59, tzinfo=TPE)
            show = None
        if now - dt.timedelta(hours=3) <= at <= now + dt.timedelta(days=days):
            out.append({"at": (show or at).isoformat(timespec="minutes"), "hasTime": show is not None,
                        "name": e["name"], "kind": e.get("kind", "")})
    return sorted(out, key=lambda x: x["at"])[:limit]


# ---------------- 文字說明 ----------------

def _md(iso):
    return f"{int(iso[5:7])}/{int(iso[8:10])}"


def _s(v, nd=1):
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):,.{nd}f}"


def read(t, adr):
    """把數字寫成幾句描述（不做預測、不給建議）。"""
    s = []
    if all(k in t for k in ("sox", "ixic", "spx")) and t["sox"].get("chg1") is not None:
        s.append(f"美股 {_md(t['sox']['date'])} 收盤：費半 {_s(t['sox']['chg1'])}%、那斯達克 {_s(t['ixic']['chg1'])}%、"
                 f"S&P 500 {_s(t['spx']['chg1'])}%。")
        x = t["sox"]
        if x.get("chg20") is not None and x.get("ma50") is not None:
            s.append(f"費半近 20 個交易日{'上漲' if x['chg20'] >= 0 else '下跌'} {abs(x['chg20']):.1f}%，"
                     f"{'在 50 日均線之上' if x['ma50'] >= 0 else '跌破 50 日均線'}（差 {abs(x['ma50']):.1f}%）。")
    if adr:
        avg = sum(v for _, v in adr) / len(adr)
        s.append(f"台積電 ADR 溢價 {adr[-1][1]:.1f}%，近 {len(adr)} 個交易日平均 {avg:.1f}%。")
    v = t.get("vix")
    if v:
        band = "平靜" if v["last"] < 15 else "正常" if v["last"] < 20 else "偏緊張" if v["last"] < 30 else "恐慌"
        s.append(f"VIX {v['last']:.1f}，市場情緒{band}（20 以下算平靜，30 以上是恐慌）。")
    parts = []
    r, dx, tw = t.get("tnx"), t.get("dxy"), t.get("twd")
    if r and r.get("d20") is not None:
        parts.append(f"美國 10 年債殖利率 {r['last']:.2f}%，近 20 日{'上升' if r['d20'] >= 0 else '下降'} {abs(r['d20']):.2f} 個百分點")
    if dx and dx.get("chg20") is not None:
        parts.append(f"美元指數近 20 日 {_s(dx['chg20'])}%")
    if tw and tw.get("chg20") is not None:
        parts.append(f"新台幣近 20 日{'貶值' if tw['chg20'] > 0 else '升值'} {abs(tw['chg20']):.1f}%（1 美元兌 {tw['last']:.2f} 元）")
    if parts:
        s.append("；".join(parts) + "。")
    for k, nm in (("wti", "原油"), ("gold", "黃金")):
        x = t.get(k)
        if x and x.get("chg5") is not None and abs(x["chg5"]) >= 5:
            s.append(f"{nm}近 5 個交易日{'大漲' if x['chg5'] > 0 else '大跌'} {abs(x['chg5']):.1f}%。")
    return s


# ---------------- 每天更新 ----------------

def _fomc(now, problems):
    """會議日程每週重抓一次，存在 data/meta/fomc.json；抓不到就用上次的。"""
    cache = store.load_meta("fomc", {}) or {}
    age = store.meta_age_days("fomc")
    if cache.get("meetings") and age is not None and age < 7:
        return cache["meetings"]
    try:
        meetings = parse_fomc(get_text(FOMC_URL, retries=2))
        store.save_meta("fomc", {"_saved": now.date().isoformat(), "meetings": meetings})
        return meetings
    except FetchError as e:
        print("  聯準會會議日程下載失敗，先用上次的：", e)
    except DataError as e:
        problems.append(str(e))
    return cache.get("meetings") or []


def _manual(problems):
    try:
        with open(EVENTS, encoding="utf-8") as f:
            ev = json.load(f)["events"]
        for e in ev:
            dt.date.fromisoformat(e["date"])
            if e.get("time"):
                ZoneInfo(e.get("tz") or "Asia/Taipei")
        return ev
    except FileNotFoundError:
        return []
    except Exception as e:  # noqa: BLE001
        problems.append(f"events.json 格式不對：{e!r}")
        return []


def update(now, tw_close, fetch_json=None):
    """抓最新資料，整理成網頁要用的數字，存到 data/meta/macro.json。回傳 (資料, 問題清單)。
    tw_close：{日期: 台積電台股收盤}（算 ADR 溢價用）。"""
    fetch_json = fetch_json or (lambda u: get_json(u, retries=2))
    problems = []
    old = store.load_meta("macro", {}) or {}
    old_tiles = old.get("tiles") or {}
    raw, older = {}, set()
    for key, sym, name, _, (lo, hi) in SYMBOLS:
        try:
            s = parse_chart(fetch_json(CHART.format(urllib.parse.quote(sym))), now.timestamp())
            if len(s) < 25:
                raise DataError(f"{name}只有 {len(s)} 天資料，Yahoo 回應可能改了")
            if not lo <= s[-1][1] <= hi:
                raise DataError(f"{name}最新值 {s[-1][1]} 不在合理範圍，資料可能有問題")
            if (now.date() - dt.date.fromisoformat(s[-1][0])).days > 7:
                raise DataError(f"{name}最新資料停在 {s[-1][0]}，Yahoo 可能已經不更新這個代號")
            prev = (old_tiles.get(key) or {}).get("date")
            if prev and s[-1][0] < prev:
                # Yahoo 偶爾回傳少了最後一天的資料（10/30、10/31 早上都發生過）：上次的比較新，整格沿用，ADR 溢價也不重算
                older.add(key)
                continue
            raw[key] = s
        except FetchError as e:
            print(f"  {name}下載失敗：{e}")
        except DataError as e:
            problems.append(str(e))
    tiles = {}
    for key, _, name, unit, _ in SYMBOLS:
        if key in raw:
            tiles[key] = dict(stats(raw[key]), name=name, unit=unit)
        elif key in older:
            tiles[key] = old_tiles[key]
        elif key in old_tiles:
            tiles[key] = dict(old_tiles[key], stale=True)  # 這次沒抓到：用上次的，網頁會註明日期
    adr = adr_premium(raw.get("tsm"), raw.get("twd"), tw_close)
    if not adr and old.get("adr"):
        adr = [tuple(x) for x in old["adr"]]
    manual = _manual(problems)
    if manual and max(e["date"] for e in manual) < (now.date() + dt.timedelta(days=60)).isoformat():
        print("  提醒：events.json 只登記到", max(e["date"] for e in manual), "，記得補上之後的 CPI、非農與央行日期")
    m = {"tiles": tiles, "adr": [list(x) for x in adr], "events": upcoming(now, _fomc(now, problems), manual),
         "read": read(tiles, adr), "missing": [NAMES[k] for k in NAMES if k not in raw and k not in older]}
    strip = lambda x: {k: v for k, v in x.items() if k not in ("asOf", "_saved")}  # noqa: E731
    same = old.get("asOf") and json.dumps(strip(old), sort_keys=True) == json.dumps(strip(m), sort_keys=True)
    m["asOf"] = old["asOf"] if same else now.isoformat(timespec="minutes")  # 數字沒變就不改時間，網頁才不會每次都變
    store.save_meta("macro", m)
    return m, problems
