"""國際盤勢「最近公布的結果」：之前的大事公布了什麼，以及當晚美股、接著台股怎麼動。

每一種事件只留最近一次（Fed 利率決策、美國 CPI、非農就業、台灣央行），下一次公布才換掉；
選舉這種一次性的留 30 天。

結果從哪裡來：
- Fed：聯準會的會後聲明（決策日美東時間下午 2 點公布）
- CPI、非農：美國勞工統計局的公開資料 API（不用金鑰；一次請求拿齊要的數列，未註冊每天限 25 次）
- 台灣央行、選舉：沒有固定格式，手動寫在 events.json 的 result（一句話）
- 市場反應：S&P 500、10 年債殖利率用 macro.py 已經抓的 Yahoo 走勢，台股用自己存的加權指數漲跌

算好的存在 data/meta/event_results.json，完整之後就不再重抓。這裡只描述發生了什麼，
不放進分數，也不判斷是好是壞（市場原本預期多少是付費資料，抓不到）。
"""
import datetime as dt
import html as htmllib
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from . import store
from .checks import DataError
from .net import FetchError, decode, fetch, get_text

NY = ZoneInfo("America/New_York")
FED_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{}a.htm"
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
# CPI：全部項目、扣掉食物和能源（都是未季調，年增率和官方公布的一樣）；非農：就業人數（千人，季調）、失業率（季調）
SERIES = {"cpi": ("CUUR0000SA0", "CUUR0000SA0L1E"), "nfp": ("CES0000000001", "LNS14000000")}
LATEST = ("fomc", "cpi", "nfp", "cbc")  # 每種留最近一次
AUTO = ("fomc", "cpi", "nfp")           # 結果自動抓的種類
ONE_OFF_DAYS = 30     # 其他（選舉）留幾天
MAX_AGE_DAYS = 120    # 「最近一次」太舊（events.json 漏登記）就不顯示
RETRY_DAYS = 60       # 超過這麼久還沒抓到結果或市場反應，就不再試（Fed 最長約 8 週開一次會）
KEEP_DAYS = 400       # event_results.json 留多久
REACT = {"cbc": "tw", "election": "next"}  # 其他種類：當晚美股＋接著的台股


def group(kind):
    return "fomc" if kind.startswith("fomc") else kind


# ---------------- 聯準會聲明 ----------------

def _plain(html):
    t = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", html)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", t))
    t = t.replace("‐", "-").replace("‑", "-").replace("⁄", "/")
    return re.sub(r"\s+", " ", t)


def _frac(s):
    """聯準會寫利率的方式：3-3/4 → 3.75、1/4 → 0.25、4 → 4。"""
    m = re.fullmatch(r"(\d+)(?:-(\d+)/(\d+))?|(\d+)/(\d+)", s.strip())
    if not m:
        raise DataError(f"聯準會聲明裡的利率寫法看不懂：{s}")
    if m.group(4):
        return int(m.group(4)) / int(m.group(5))
    return int(m.group(1)) + (int(m.group(2)) / int(m.group(3)) if m.group(2) else 0)


DECIDE = re.compile(r"decided to (maintain|raise|lower) the target range for the federal funds rate"
                    r"(?: by ([\d/-]+) percentage point)? (?:at|to) ([\d/-]+) to ([\d/-]+) percent")


def _dissent(t):
    """「Voting against ... were A and B, who preferred to raise ... by 1/4 percentage point at this meeting; and C, who
    preferred no change ...」→ [{"n": 人數, "way": raise/lower/hold, "by": 百分點}]。"""
    i = t.find("Voting against")
    if i < 0:
        return []
    seg = t[i:i + 1200]
    j = seg.find("meeting.")
    if j >= 0:
        seg = seg[:j + 8]
    seg = re.sub(r"^Voting against (?:the|this) (?:monetary policy )?action (?:was|were) ", "", seg)
    out = []
    for part in re.split(r";\s*(?:and\s+)?", seg):
        m = re.match(r"(.+?),? who preferred (.*)", part)
        if not m:
            continue
        names = [x for x in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1)) if x.strip()]
        p = m.group(2)
        way = ("raise" if re.search(r"\b(?:raise|increase)", p) else "lower" if re.search(r"\b(?:lower|reduc|cut)", p)
               else "hold" if re.search(r"no change|maintain|leave", p) else None)
        b = re.search(r"by ([\d/-]+) percentage point", p)
        bp = re.search(r"by (\d+) basis points", p)
        out.append({"n": len(names), "way": way, "by": _frac(b.group(1)) if b else int(bp.group(1)) / 100 if bp else None})
    return out


def parse_fed(html):
    """聯準會會後聲明 → {"way": hold/raise/lower, "by": 調幅（百分點）, "lo", "hi": 目標區間（%）,
    "for", "against": 贊成／反對票數, "dissent": 反對的人主張什麼}。"""
    t = _plain(html)
    m = DECIDE.search(t)
    if not m:
        raise DataError("聯準會聲明裡找不到利率決策那句話，網頁可能改版")
    out = {"way": "hold" if m.group(1) == "maintain" else m.group(1), "by": _frac(m.group(2)) if m.group(2) else None,
           "lo": _frac(m.group(3)), "hi": _frac(m.group(4))}
    if not 0 <= out["lo"] < out["hi"] <= 25:
        raise DataError(f"聯準會聲明裡的利率區間看起來不對：{m.group(0)}")
    v = re.search(r"by an? (\d+)\s*[-–—]\s*(\d+) vote", t)
    if v:
        out["for"], out["against"] = int(v.group(1)), int(v.group(2))
    out["dissent"] = _dissent(t)
    return out


def _ma(by):
    """調幅換成「碼」（1 碼 = 0.25 個百分點）。"""
    n = by / 0.25
    return f"{round(n)} 碼" if abs(n - round(n)) < 1e-9 else f"{by:g} 個百分點"


def _pref(d):
    w = d.get("way")
    if w == "hold":
        return "不動"
    if w in ("raise", "lower"):
        return ("升" if w == "raise" else "降") + (f" {_ma(d['by'])}" if d.get("by") else "息")
    return "其他做法"


def fed_text(r):
    rng = f"{r['lo']:.2f}%～{r['hi']:.2f}%"
    if r["way"] == "hold":
        s = f"維持 {rng} 不變"
    else:
        s = ("升息" if r["way"] == "raise" else "降息") + (f" {_ma(r['by'])}" if r.get("by") else "") + f"到 {rng}"
    ds = r.get("dissent") or []
    against = r.get("against")
    if against is None:
        against = sum(d["n"] for d in ds)
    vote = f"{r['for']} 比 {against}" if r.get("for") is not None else ""
    if not against:
        note = f"{vote} 全票通過" if vote else ""
    else:
        if len(ds) == 1 and ds[0]["n"] == against:
            who = f"反對的 {against} 位主張{_pref(ds[0])}"
        elif ds and sum(d["n"] for d in ds) == against:
            who = f"反對的 {against} 位：" + "、".join(f"{d['n']} 位主張{_pref(d)}" for d in ds)
        else:
            who = f"{against} 位反對"
        note = "，".join(x for x in (vote, who) if x)
    return s + (f"（{note}）" if note else "")


# ---------------- CPI、非農（勞工統計局） ----------------

def post_json(url, payload):
    raw = fetch(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, retries=2)
    try:
        return json.loads(decode(raw))
    except json.JSONDecodeError as e:
        raise FetchError(f"回傳的不是 JSON（可能暫時被擋）：{url}") from e


def parse_bls(j):
    """勞工統計局 API 的回應 → {數列代號: {"2026-09": 值}}。M13 是全年平均，不要。"""
    if not isinstance(j, dict) or "status" not in j:
        raise DataError("勞工統計局 API 回傳的格式看不懂，可能改版")
    if j["status"] != "REQUEST_SUCCEEDED":  # 例如超過每天的次數上限
        raise FetchError(f"勞工統計局 API：{j['status']} {' '.join(j.get('message') or [])}".strip())
    out = {}
    for x in (j.get("Results") or {}).get("series") or []:
        vals = {}
        for d in x.get("data") or []:
            p = str(d.get("period", ""))
            if re.fullmatch(r"M(0[1-9]|1[0-2])", p):
                try:
                    vals[f"{int(d['year']):04d}-{p[1:]}"] = float(d["value"])
                except (KeyError, TypeError, ValueError):
                    continue
        out[x.get("seriesID")] = vals
    if not any(out.values()):
        raise DataError("勞工統計局 API 回傳的資料是空的，格式可能改了")
    return out


def _ym(ym, k):
    y, m = int(ym[:4]), int(ym[5:7]) + k
    return f"{y + (m - 1) // 12:04d}-{(m - 1) % 12 + 1:02d}"


def _r1(x):
    return float(Decimal(f"{x:.6f}").quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def ref_month(e):
    """「美國 CPI（9 月）」在 2026/10 公布 → 2026-09；名稱沒寫月份就當作上個月。"""
    d = dt.date.fromisoformat(e["date"])
    m = re.search(r"（\s*(\d{1,2})\s*月\s*）", e.get("name", ""))
    if m:
        mo = int(m.group(1))
        return f"{d.year if mo < d.month else d.year - 1:04d}-{mo:02d}"
    return _ym(e["date"][:7], -1)


def cpi_result(nsa, core, ref):
    """年增率用未季調指數算（和勞工統計局公布的一樣）。ref 那個月還沒有資料 → None（還沒公布）。"""
    def yoy(s, m):
        a, b = s.get(m), s.get(_ym(m, -12))
        return _r1((a / b - 1) * 100) if a and b else None

    v = {"ref": ref, "yoy": yoy(nsa, ref), "prev": yoy(nsa, _ym(ref, -1)),
         "core": yoy(core, ref), "corePrev": yoy(core, _ym(ref, -1))}
    return v if v["yoy"] is not None and v["core"] is not None else None


def nfp_result(pay, rate, ref):
    """非農就業人數（千人，季調）的月增減和失業率。前月是這次公布時修正後的數字。"""
    p1, p2 = _ym(ref, -1), _ym(ref, -2)
    if ref not in pay or p1 not in pay or ref not in rate:
        return None
    return {"ref": ref, "chg": round(pay[ref] - pay[p1]), "prev": round(pay[p1] - pay[p2]) if p2 in pay else None,
            "rate": rate[ref], "ratePrev": rate.get(p1)}


def _n(v, nd=1):
    return f"{v:.{nd}f}".replace("-", "−")


def cpi_text(r):
    s = f"年增 {_n(r['yoy'])}%" + (f"（前月 {_n(r['prev'])}%）" if r.get("prev") is not None else "")
    return s + f"，扣掉食物和能源的核心 {_n(r['core'])}%" + (f"（前月 {_n(r['corePrev'])}%）" if r.get("corePrev") is not None else "")


def nfp_text(r):
    def wan(k):  # 千人 → 萬
        return _n(k / 10) + " 萬"

    s = (f"新增 {wan(r['chg'])}人" if r["chg"] >= 0 else f"減少 {wan(-r['chg'])}人")
    s += f"（前月 {wan(r['prev'])}）" if r.get("prev") is not None else ""
    return s + f"，失業率 {_n(r['rate'])}%" + (f"（前月 {_n(r['ratePrev'])}%）" if r.get("ratePrev") is not None else "")


TEXT = {"fomc": fed_text, "cpi": cpi_text, "nfp": nfp_text}


# ---------------- 市場反應 ----------------

def react_mode(e):
    """us：美國的事件，看當天美股和接著的台股；tw：台灣央行（台股收盤後公布），看隔天台股；
    next：選舉當天美股還沒開票，看開票隔天的美股和接著的台股。"""
    return REACT.get(group(e["kind"]), "us")


def _chg(series, d):
    """series：[(日期, 收盤)]，回傳 d 那天的（漲跌 %, 變動）。"""
    for i, (x, c) in enumerate(series):
        if x == d:
            if i == 0 or not series[i - 1][1]:
                return None, None
            p = series[i - 1][1]
            return round((c / p - 1) * 100, 2), round(c - p, 4)
    return None, None


def reaction(e, spx, tnx, taiex):
    """spx、tnx：Yahoo 的 [(美東日期, 收盤)]；taiex：{台北日期: 加權指數漲跌 %}。還沒有的部分就不填。"""
    mode, r = react_mode(e), {}
    local = e["at"].astimezone(NY).date().isoformat()
    anchor = e["date"] if mode == "tw" else local
    if mode != "tw":
        day = (local if any(d == local for d, _ in spx or []) else None) if mode == "us" else \
            next((d for d, _ in spx or [] if d > local), None)
        if day:
            r["us"] = day
            a, b = _chg(spx, day)[0], _chg(tnx or [], day)[1]
            r.update({k: v for k, v in (("spx", a), ("tnx", b)) if v is not None})
        if mode == "next":
            if not day:
                return r
            anchor = day
    t = next((d for d in sorted(taiex or {}) if d > anchor), None)
    if t and taiex[t] is not None:
        r["tw"], r["taiex"] = t, taiex[t]
    return r


def _sg(v, nd):
    x = Decimal(f"{v:.6f}").quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)
    return ("+" if x > 0 else "−" if x < 0 else "") + f"{abs(x):.{nd}f}"


def _md(iso):
    return f"{int(iso[5:7])}/{int(iso[8:10])}"


def react_text(e, r):
    parts = []
    if r.get("us"):
        x = []
        if r.get("spx") is not None:
            x.append(f"S&P 500 {_sg(r['spx'], 2)}%")
        if r.get("tnx") is not None:
            x.append("10 年債殖利率持平" if abs(r["tnx"]) < 0.005 else f"10 年債殖利率 {_sg(r['tnx'], 2)} 個百分點")
        if x:
            parts.append(("當晚美股 " if react_mode(e) == "us" else f"美股 {_md(r['us'])} ") + "、".join(x))
    if r.get("tw") and r.get("taiex") is not None:
        parts.append(f"台股 {_md(r['tw'])} {_sg(r['taiex'], 2)}%")
    return "；".join(parts)


# ---------------- 每次更新 ----------------

def pick(now, timeline):
    """要顯示的事件（新到舊）：每一種留最近一次，其他留 30 天。timeline 的 at 是有時區的時間。"""
    shown, seen = [], set()
    for e in sorted((x for x in timeline if x["at"] <= now), key=lambda x: x["at"], reverse=True):
        g, age = group(e["kind"]), now - e["at"]
        if g in LATEST:
            if g in seen or age > dt.timedelta(days=MAX_AGE_DAYS):
                continue
            seen.add(g)
        elif age > dt.timedelta(days=ONE_OFF_DAYS):
            continue
        shown.append(e)
    return shown


def _item(e, g, r, fresh):
    it = {"at": e["at"].isoformat(timespec="minutes"), "hasTime": e["hasTime"], "name": e["name"], "kind": e["kind"]}
    res = e.get("result") or (TEXT[g](r["res"]) if r.get("res") and g in TEXT else None)
    rt = react_text(e, r.get("react") or {})
    if res:
        it["result"] = res
    elif g in AUTO:
        it["pending"] = "結果還沒抓到，下次更新會再試。" if fresh else "這次的結果沒抓到。"
    elif not rt:
        it["pending"] = "結果還沒整理。"
    if rt:
        it["react"] = rt
    return it


def _key(e):
    return f"{group(e['kind'])}:{e['date']}"


def update(now, timeline, series, taiex, fetch_text=None, problems=None, post=None):
    """回傳「最近公布的結果」（新到舊），順便把新抓到的存進 data/meta/event_results.json。
    series：macro.py 這次抓到的 Yahoo 走勢 {"spx": [...], "tnx": [...]}（沒抓到的就沒有）。"""
    fetch_text = fetch_text or (lambda u: get_text(u, retries=2))
    post = post or post_json
    problems = problems if problems is not None else []
    saved = store.load_meta("event_results", {}) or {}
    rec = {k: dict(v) for k, v in saved.items()}
    shown = pick(now, timeline)

    def todo(e):  # 還要自動抓結果的
        return (group(e["kind"]) in AUTO and not e.get("result") and not (rec.get(_key(e)) or {}).get("res")
                and now - e["at"] <= dt.timedelta(days=RETRY_DAYS))

    need = [e for e in shown if todo(e) and group(e["kind"]) in SERIES]
    bls = None
    if need:  # CPI、非農一次請求拿齊（API 每天有次數上限）
        ids = sorted({s for e in need for s in SERIES[group(e["kind"])]})
        years = [int(ref_month(e)[:4]) for e in need]
        try:
            bls = parse_bls(post(BLS_URL, {"seriesid": ids, "startyear": str(min(years) - 2), "endyear": str(max(years))}))
        except FetchError as err:
            print(f"  勞工統計局的數字還沒抓到：{err}")
        except DataError as err:
            problems.append(str(err))

    out = []
    for e in shown:
        g, key = group(e["kind"]), _key(e)
        r = rec.get(key) or {}
        fresh = now - e["at"] <= dt.timedelta(days=RETRY_DAYS)
        if todo(e):
            v = None
            if g == "fomc":
                try:
                    v = parse_fed(fetch_text(FED_URL.format(e["date"].replace("-", ""))))
                except FetchError as err:
                    print(f"  {e['name']}的結果還沒抓到：{err}")
                except DataError as err:
                    problems.append(f"{e['name']}：{err}")
            elif bls is not None:
                a, b = (bls.get(x) or {} for x in SERIES[g])
                v = (cpi_result if g == "cpi" else nfp_result)(a, b, ref_month(e))
                if not v:
                    print(f"  {e['name']}：勞工統計局還沒有 {ref_month(e)} 的數字，下次再試")
            if v:
                r["res"] = v
        old = r.get("react") or {}
        if fresh and not old.get("done"):
            new = reaction(e, series.get("spx"), series.get("tnx"), taiex)
            m = dict(old, **{k: v for k, v in new.items() if v is not None})
            m.pop("done", None)
            if "tw" in m and (react_mode(e) == "tw" or "us" in m):
                m["done"] = True
            if m:
                r["react"] = m
        if r:
            rec[key] = r
        out.append(_item(e, g, r, fresh))
    cutoff = (now - dt.timedelta(days=KEEP_DAYS)).date().isoformat()
    rec = {k: v for k, v in rec.items() if k.split(":", 1)[-1] >= cutoff}
    if rec != saved:
        store.save_meta("event_results", rec)
    return out
