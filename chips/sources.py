"""各官方資料來源的下載與解析。

全部回傳 Python dict，股數一律是「股」，融資融券餘額是「張」。資料尚未公布或當天休市時回傳 None。
欄位盡量用欄位名稱對應（網站改版調整欄位順序時比較不會錯），找不到名稱才用已知的欄位位置。
"""
import datetime as dt
import http.cookiejar
import re
import urllib.request

from .checks import DataError
from .net import FetchError, fetch, get_json, get_text, decode

TWSE = "https://www.twse.com.tw/rwd/zh"
TPEX = "https://www.tpex.org.tw/www/zh-tw"


def num(s):
    """把 "1,234"、"+0.50"、"--" 之類的字串轉成數字；無法轉換時回傳 None。"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    if s in ("", "-", "--", "---", "X", "除權息", "除權", "除息"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def z(s):
    v = num(s)
    return 0.0 if v is None else v


def is_common_stock(code):
    """四碼、開頭不是 0 的代號視為普通股（排除 ETF、權證、債券）。"""
    return bool(re.fullmatch(r"[1-9]\d{3}", code))


def _ok(j):
    if not isinstance(j, dict):
        return False
    stat = str(j.get("stat", "")).lower()
    has_rows = bool(j.get("data")) or any(t.get("data") for t in (j.get("tables") or []) if isinstance(t, dict))
    return stat == "ok" and has_rows


def _col(fields, names, fallback):
    """在欄位名稱中找第一個完全相同的名稱，找不到就用 fallback 位置。"""
    clean = [re.sub(r"<[^>]+>", "", str(f)).strip() for f in (fields or [])]
    for n in names:
        if n in clean:
            return clean.index(n)
    for n in names:
        for i, f in enumerate(clean):
            if f.startswith(n):
                return i
    return fallback


def _expect(fields, spec, what):
    """用固定欄位位置解析的資料表，先確認那些位置的欄位名稱沒變；變了就是網站改版，丟出 DataError。"""
    clean = [re.sub(r"<[^>]+>|\s", "", str(f)) for f in (fields or [])]
    for i, name in spec.items():
        if i >= len(clean) or not clean[i].startswith(name):
            got = clean[i] if i < len(clean) else "（沒有這一欄）"
            raise DataError(f"{what}第 {i + 1} 欄應該是「{name}」，現在是「{got}」，網站可能改版")


def _get(url):
    """有資料回傳 JSON；網站回覆「沒有資料」回傳 None；連線失敗則丟出 FetchError（不能當成休市）。"""
    j = get_json(url)
    return j if _ok(j) else None


def _tables(j, first_field=None, must_have=None):
    for t in (j or {}).get("tables") or []:
        f = [re.sub(r"<[^>]+>", "", str(x)).strip() for x in (t.get("fields") or [])]
        if first_field and (not f or f[0] != first_field):
            continue
        if must_have and must_have not in f:
            continue
        yield t


def _roc(d):
    return f"{d.year - 1911}/{d:%m/%d}"


# ---------------- 證交所（上市） ----------------

def twse_inst(d):
    """三大法人買賣超（個股）：{代號: {name, foreign, trust, dealer, total}}，單位：股。"""
    j = _get(f"{TWSE}/fund/T86?date={d:%Y%m%d}&selectType=ALLBUT0999&response=json")
    if not j or not j.get("data"):
        return None
    f = j.get("fields") or []
    c_fx = _col(f, ["外陸資買賣超股數(不含外資自營商)"], 4)
    c_fd = _col(f, ["外資自營商買賣超股數"], 7)
    c_it = _col(f, ["投信買賣超股數"], 10)
    c_dl = _col(f, ["自營商買賣超股數"], 11)
    c_tot = _col(f, ["三大法人買賣超股數"], len(f) - 1 if f else 18)
    out = {}
    for r in j["data"]:
        code = str(r[0]).strip()
        if not is_common_stock(code):
            continue
        out[code] = {"name": str(r[1]).strip(), "foreign": z(r[c_fx]) + z(r[c_fd]), "trust": z(r[c_it]),
                     "dealer": z(r[c_dl]), "total": z(r[c_tot])}
    return out


TWSE_INDEX_NAMES = {
    "發行量加權股價指數": "加權指數",
    "半導體類指數": "半導體",
    "電子工業類指數": "電子",
    "金融保險類指數": "金融",
    "航運類指數": "航運",
    "生技醫療類指數": "生技",
}


def twse_quotes(d):
    """每日收盤行情：(個股 {代號: {...}}, 指數 {顯示名稱: {close, chg, chgPct}}, 大盤統計 {value 總成交金額})。"""
    j = _get(f"{TWSE}/afterTrading/MI_INDEX?date={d:%Y%m%d}&type=ALLBUT0999&response=json")
    if not j:
        return None, None, None
    t = next(_tables(j, "證券代號", "收盤價"), None)
    if not t:
        return None, None, None
    f = t["fields"]
    c = {k: _col(f, [n], i) for k, n, i in (("vol", "成交股數", 2), ("amt", "成交金額", 4), ("open", "開盤價", 5),
                                            ("high", "最高價", 6), ("low", "最低價", 7), ("close", "收盤價", 8),
                                            ("sign", "漲跌(+/-)", 9), ("diff", "漲跌價差", 10))}
    stocks = {}
    for r in t["data"]:
        code = str(r[0]).strip()
        if not is_common_stock(code):
            continue
        sign_txt = str(r[c["sign"]])
        sign = -1 if ("-" in re.sub(r"<[^>]+>", "", sign_txt) or "green" in sign_txt) else 1
        diff = num(r[c["diff"]])
        stocks[code] = {"name": str(r[1]).strip(), "close": num(r[c["close"]]), "open": num(r[c["open"]]),
                        "high": num(r[c["high"]]), "low": num(r[c["low"]]), "vol": z(r[c["vol"]]),
                        "amt": z(r[c["amt"]]), "diff": None if diff is None else sign * diff,
                        "exRight": "X" in re.sub(r"<[^>]+>", "", sign_txt)}
    indices = {}
    for t in _tables(j, "指數"):
        for r in t.get("data") or []:
            name = re.sub(r"<[^>]+>", "", str(r[0])).strip()
            short = TWSE_INDEX_NAMES.get(name)
            if not short or short in indices:
                continue
            sign_txt = str(r[2]) if len(r) > 2 else ""
            sign = -1 if ("green" in sign_txt or "-" in re.sub(r"<[^>]+>", "", sign_txt)) else 1
            close, pts, pct = num(r[1]), num(r[3]), num(r[4])
            if close is None:
                continue
            indices[short] = {"close": close, "chg": round(sign * abs(pts or 0), 2), "chgPct": round(sign * abs(pct or 0), 2)}
    stats = {}
    st = next(_tables(j, "成交統計"), None)
    if st and st.get("data"):
        row = next((r for r in st["data"] if str(r[0]).strip().startswith("總計")), st["data"][-1])
        stats["value"] = z(row[1])  # 大盤成交金額（元），新聞說的「成交量 X 億」就是這個
    return stocks, indices, stats


def twse_margin(d):
    """融資融券餘額：({代號: {mBal, mChg, sBal, sChg}} 單位張, {amt, amtPrev} 全市場融資金額，單位仟元)。
    約晚上 9 點半公布。"""
    j = _get(f"{TWSE}/marginTrading/MI_MARGN?date={d:%Y%m%d}&selectType=ALL&response=json")
    if not j:
        return None, None
    t = next((t for t in _tables(j, "代號") if len(t.get("data") or []) > 50), None)
    if not t:
        return None, None
    _expect(t.get("fields"), {0: "代號", 5: "前日餘額", 6: "今日餘額", 11: "前日餘額", 12: "今日餘額"}, "證交所融資融券")
    out = {}
    for r in t["data"]:
        code = str(r[0]).strip()
        if not is_common_stock(code) or len(r) < 13:
            continue
        out[code] = {"mBal": z(r[6]), "mChg": z(r[6]) - z(r[5]), "sBal": z(r[12]), "sChg": z(r[12]) - z(r[11])}
    summary = None
    for st in _tables(j, "項目"):
        for r in st.get("data") or []:
            if str(r[0]).strip().startswith("融資金額") and len(r) >= 6:
                summary = {"amtPrev": z(r[4]), "amt": z(r[5])}
    return out, summary


def twse_daytrade(d):
    """當日沖銷交易標的：{代號: {dtVol 當沖成交股數, noShortFirst 暫停先賣後買}}。"""
    j = _get(f"{TWSE}/dayTrading/TWTB4U?date={d:%Y%m%d}&selectType=All&response=json")
    out = {}
    for t in _tables(j, "證券代號"):
        for r in t.get("data") or []:
            code = str(r[0]).strip()
            if is_common_stock(code) and len(r) > 3:
                out[code] = {"dtVol": z(r[3]), "noShortFirst": str(r[2]).strip().upper() == "Y"}
    return out or None


def twse_flows(d):
    """三大法人買賣金額（上市整體）：{外資, 投信, 自營商, 合計}，單位：元。"""
    j = _get(f"{TWSE}/fund/BFI82U?type=day&dayDate={d:%Y%m%d}&response=json")
    if not j:
        return None
    out = {}
    for r in j.get("data") or []:
        name, net = str(r[0]).strip(), z(r[3])
        key = next((k for k in ("自營商", "投信", "外資", "合計") if name.startswith(k)), None)
        if key:
            out[key] = out.get(key, 0) + net  # 外資 = 外資及陸資 + 外資自營商；自營商 = 自行買賣 + 避險
    return out or None


def twse_companies():
    """上市公司基本資料：{代號: {industry 產業代碼, shares 已發行普通股數}}。"""
    rows = get_json("https://openapi.twse.com.tw/v1/opendata/t187ap03_L")
    out = {}
    for r in rows or []:
        code = str(r.get("公司代號", "")).strip()
        if code:
            out[code] = {"industry": str(r.get("產業別", "")).strip(),
                         "shares": z(r.get("已發行普通股數或TDR原股發行股數"))}
    return out


# ---------------- 櫃買中心（上櫃） ----------------

def tpex_inst(d):
    j = _get(f"{TPEX}/insti/dailyTrade?type=Daily&sect=EW&date={d:%Y/%m/%d}&response=json")
    if not j:
        return None
    _expect(j["tables"][0].get("fields"), {0: "代號", 10: "買賣超股數", 13: "買賣超股數", 22: "買賣超股數", 23: "三大法人買賣超"},
            "櫃買中心三大法人")
    out = {}
    for r in j["tables"][0]["data"]:
        code = str(r[0]).strip()
        if not is_common_stock(code) or len(r) < 24:
            continue
        out[code] = {"name": str(r[1]).strip(), "foreign": z(r[10]), "trust": z(r[13]),
                     "dealer": z(r[22]), "total": z(r[23])}
    return out


def tpex_quotes(d):
    j = _get(f"{TPEX}/afterTrading/otc?date={d:%Y/%m/%d}&type=EW&response=json")
    if not j:
        return None
    t = j["tables"][0]
    f = t.get("fields") or []
    c = {k: _col(f, n, i) for k, n, i in (("close", ["收盤"], 2), ("diff", ["漲跌"], 3), ("open", ["開盤"], 4),
                                         ("high", ["最高"], 5), ("low", ["最低"], 6), ("vol", ["成交股數"], 7),
                                         ("amt", ["成交金額(元)", "成交金額"], 8), ("shares", ["發行股數"], 14))}
    out = {}
    for r in t["data"]:
        code = str(r[0]).strip()
        if not is_common_stock(code) or len(r) <= max(c.values()):
            continue
        out[code] = {"name": str(r[1]).strip(), "close": num(r[c["close"]]), "open": num(r[c["open"]]),
                     "high": num(r[c["high"]]), "low": num(r[c["low"]]), "vol": z(r[c["vol"]]),
                     "amt": z(r[c["amt"]]), "diff": num(r[c["diff"]]), "shares": z(r[c["shares"]]),
                     "exRight": False}
    return out


def tpex_index(d):
    """櫃買指數收盤：{close, chg, chgPct}。"""
    j = _get(f"{TPEX}/indexInfo/inx?date={d:%Y/%m/%d}&response=json")
    if not j:
        return None
    keys = {f"{d:%Y/%m/%d}", _roc(d), f"{d:%Y%m%d}"}
    for t in j.get("tables") or []:
        for r in t.get("data") or []:
            if str(r[0]).strip() in keys and len(r) > 5:
                close, chg = num(r[4]), num(r[5])
                if close:
                    chg = chg or 0
                    return {"close": close, "chg": round(chg, 2),
                            "chgPct": round(chg / (close - chg) * 100, 2) if close != chg else 0}
    return None


def tpex_margin(d):
    j = _get(f"{TPEX}/margin/balance?date={d:%Y/%m/%d}&response=json")
    if not j:
        return None
    _expect(j["tables"][0].get("fields"), {0: "代號", 2: "前資餘額", 6: "資餘額", 10: "前券餘額", 14: "券餘額"}, "櫃買中心融資融券")
    out = {}
    for r in j["tables"][0]["data"]:
        code = str(r[0]).strip()
        if not is_common_stock(code) or len(r) < 15:
            continue
        out[code] = {"mBal": z(r[6]), "mChg": z(r[6]) - z(r[2]), "sBal": z(r[14]), "sChg": z(r[14]) - z(r[10])}
    return out


def tpex_daytrade(d):
    j = _get(f"{TPEX}/intraday/stat?type=Daily&date={d:%Y/%m/%d}&response=json")
    out = {}
    for t in _tables(j, "證券代號"):
        for r in t.get("data") or []:
            code = str(r[0]).strip()
            if is_common_stock(code) and len(r) > 3:
                out[code] = {"dtVol": z(r[3]), "noShortFirst": str(r[2]).strip().upper() == "Y"}
    return out or None


def tpex_companies():
    rows = get_json("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O")
    out = {}
    for r in rows or []:
        code = str(r.get("SecuritiesCompanyCode") or r.get("公司代號") or "").strip()
        ind = str(r.get("SecuritiesIndustryCode") or r.get("產業別") or "").strip()
        if code:
            out[code] = {"industry": ind}
    return out


# ---------------- 公開資訊觀測站：月營收 ----------------

def mops_revenue(y, m):
    """某年某月的月營收彙總表（上市、上櫃，含外國公司）：{代號: [當月營收, 去年當月營收]}，單位千元。
    抓不到回傳空 dict（例如還沒公布）。"""
    out = {}
    for mk in ("sii", "otc"):
        for k in (0, 1):
            raw = None
            for host in ("https://mopsov.twse.com.tw", "https://mops.twse.com.tw"):
                try:
                    raw = fetch(f"{host}/nas/t21/{mk}/t21sc03_{y - 1911}_{m}_{k}.html", retries=2, timeout=60)
                    break
                except FetchError:
                    continue
            if raw is None:
                continue
            html = raw.decode("cp950", errors="replace")
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
                td = [re.sub(r"<[^>]+>|&nbsp;|\s", "", x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
                if len(td) < 10 or not re.fullmatch(r"\d{4}", td[0]):
                    continue
                rev, ly = num(td[2]), num(td[4])
                if rev is not None:
                    out[td[0]] = [rev, ly]
    return out


# ---------------- 注意股、處置股 ----------------

def _roc_date(s):
    """民國日期 "115.10.22"、"115/10/22"、"1151022" → date；看不懂回傳 None。"""
    s = re.sub(r"<[^>]+>", "", str(s)).strip()
    m = re.fullmatch(r"(\d{2,3})[./](\d{1,2})[./](\d{1,2})", s) or re.fullmatch(r"(\d{3})(\d{2})(\d{2})", s)
    if not m:
        return None
    y, mo, dd = (int(x) for x in m.groups())
    try:
        return dt.date(y + 1911, mo, dd)
    except ValueError:
        return None


def _period(s):
    """處置起迄 "115/10/20～115/10/27"、"1151022~1151029" → (起, 迄)。"""
    parts = re.split(r"\s*[~～]\s*", re.sub(r"<[^>]+>", "", str(s)).strip())
    return (_roc_date(parts[0]), _roc_date(parts[1])) if len(parts) == 2 else (None, None)


def _why(s):
    """注意原因只留第一項，去掉「（第一款）」之類的條文編號。"""
    s = re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "；", str(s), flags=re.I))
    s = re.sub(r"[﹝（(]第[一二三四五六七八九十]+款[﹞）)]", "", s)
    s = re.split(r"[；。]", s)[0].strip()
    return s if len(s) <= 45 else s[:44] + "…"


def _cn_num(s):
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    d = {c: i for i, c in enumerate("零一二三四五六七八九")}
    if "十" in s:
        a, _, b = s.partition("十")
        return (d.get(a, 1) if a else 1) * 10 + (d.get(b, 0) if b else 0)
    return d.get(s)


def _measure(text):
    """處置內容裡的撮合間隔（分鐘）與是否要先收足款券。"""
    t = re.sub(r"<[^>]+>", "", str(text))
    m = re.search(r"約每\s*([0-9０-９一二三四五六七八九十]+)\s*分鐘撮合一次", t)
    return (_cn_num(m.group(1)) if m else None), bool(re.search(r"收取全部之買進價金|預收", t))


def _need_cols(fields, spec, what):
    """spec：{key: [欄位名稱…]}。任何一個找不到就當作網站改版。"""
    out = {}
    for k, names in spec.items():
        i = _col(fields, names, None)
        if i is None:
            raise DataError(f"{what}找不到「{names[0]}」欄位，網站可能改版")
        out[k] = i
    return out


def _alert_rows(j, what, first_field=None):
    """回傳 (欄位, 資料列)。網站回覆「沒有資料」時回傳空列；看不懂的回應丟出 DataError。"""
    if not isinstance(j, dict):
        raise DataError(f"{what}回應不是預期的格式")
    stat = str(j.get("stat", ""))
    if "tables" in j:
        for t in _tables(j, first_field):
            return t.get("fields") or [], t.get("data") or []
        if stat.lower() == "ok" and not any(t.get("data") for t in j["tables"] if isinstance(t, dict)):
            return [], []
        raise DataError(f"{what}找不到資料表，網站可能改版")
    if stat.upper() == "OK":
        return j.get("fields") or [], j.get("data") or []
    if "沒有符合" in stat or "查無" in stat:
        return [], []
    raise DataError(f"{what}回應看不懂：{stat[:40]}")


def _notice(rows, f, what):
    if not rows:
        return {}
    c = _need_cols(f, {"code": ["證券代號"], "why": ["注意交易資訊"], "date": ["日期", "公告日期"]}, what)
    out = {}
    for r in rows:
        code, d = str(r[c["code"]]).strip(), _roc_date(r[c["date"]])
        if d is None:
            raise DataError(f"{what}的日期看不懂：{r[c['date']]}")
        if is_common_stock(code):
            out.setdefault(d.isoformat(), {})[code] = _why(r[c["why"]])
    return out


def twse_notice(start, end):
    """證交所公布的注意股：{日期: {代號: 原因}}。沒有注意股的日子不會出現在結果裡。"""
    what = "證交所注意股"
    j = get_json(f"{TWSE}/announcement/notice?querytype=1&stockNo=&selectType=&startDate={start:%Y%m%d}"
                 f"&endDate={end:%Y%m%d}&response=json")
    f, rows = _alert_rows(j, what)
    prm = j.get("params") or {}
    if prm and (prm.get("startDate"), prm.get("endDate")) != (f"{start:%Y%m%d}", f"{end:%Y%m%d}"):
        raise DataError(f"{what}回傳的日期範圍不是查詢的範圍")
    return _notice(rows, f, what)


def tpex_notice(start, end):
    what = "櫃買中心注意股"
    j = get_json(f"{TPEX}/bulletin/attention?startDate={start:%Y/%m/%d}&endDate={end:%Y/%m/%d}&response=json")
    f, rows = _alert_rows(j, what)
    if rows and j.get("date") and j["date"] != f"{start:%Y%m%d}~{end:%Y%m%d}":
        raise DataError(f"{what}回傳的日期範圍 {j['date']} 不是查詢的範圍")
    return _notice(rows, f, what)


def _punish(rows, f, what, spec):
    if not rows:
        return []
    c = _need_cols(f, spec, what)
    out = []
    for r in rows:
        code = str(r[c["code"]]).strip()
        if not is_common_stock(code):
            continue
        ann = _roc_date(r[c["ann"]])
        start, end = _period(r[c["period"]])
        if not (ann and start and end):
            raise DataError(f"{what}的日期看不懂：{r[c['ann']]} {r[c['period']]}")
        mins, prepay = _measure(r[c["detail"]])
        out.append({"code": code, "ann": ann.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                    "step": re.sub(r"<[^>]+>", "", str(r[c["step"]])).strip(), "mins": mins, "prepay": prepay})
    return out


def twse_punish(start, end):
    """證交所處置股（依公布日期查詢）：[{code, ann 公布日, start, end 處置起迄, step 第幾次處置, mins 撮合間隔, prepay 是否先收款}]"""
    what = "證交所處置股"
    j = get_json(f"{TWSE}/announcement/punish?querytype=3&stockNo=&selectType=&proceType=&remarkType="
                 f"&startDate={start:%Y%m%d}&endDate={end:%Y%m%d}&response=json")
    f, rows = _alert_rows(j, what)
    return _punish(rows, f, what, {"code": ["證券代號"], "ann": ["公布日期"], "period": ["處置起迄時間", "處置起訖時間"],
                                   "step": ["處置措施"], "detail": ["處置內容"]})


def tpex_punish(start, end):
    what = "櫃買中心處置股"
    j = get_json(f"{TPEX}/bulletin/disposal?startDate={start:%Y/%m/%d}&endDate={end:%Y/%m/%d}&response=json")
    f, rows = _alert_rows(j, what)
    return _punish(rows, f, what, {"code": ["證券代號"], "ann": ["公布日期"], "period": ["處置起訖時間", "處置起迄時間"],
                                   "step": ["處置措施"], "detail": ["處置內容"]})


# ---------------- 集保結算所 ----------------

def tdcc_latest():
    """集保戶股權分散表開放資料（只有最新一週）：(資料日 YYYYMMDD, {代號: 千張大戶持股 %},
    {代號: [股東人數, 千張以上 %, 400 張以上 %, 50 張以下 %]})。第三項每週存下來，累積夠了再回測股東人數的效果。"""
    text = get_text("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5")
    big, acc, date = {}, {}, None
    for line in text.splitlines()[1:]:
        p = [x.strip() for x in line.split(",")]
        if len(p) < 6 or not is_common_stock(p[1]) or not p[2].isdigit():
            continue
        date = date or p[0]
        lvl, holders, pct = int(p[2]), num(p[3]), num(p[5])
        a = acc.setdefault(p[1], {"h": None, "p15": None, "p400": 0.0, "p50": 0.0})
        if pct is None:
            continue
        if lvl == 15:  # 第 15 級：1,000,001 股以上（千張大戶）
            big[p[1]] = a["p15"] = pct
        if 12 <= lvl <= 15:  # 400 張以上
            a["p400"] += pct
        if 1 <= lvl <= 8:  # 50 張以下
            a["p50"] += pct
        if pct >= 99.9 and lvl >= 16:  # 合計列
            a["h"] = holders
    full = {c: [a["h"], a["p15"], round(a["p400"], 2), round(a["p50"], 2)] for c, a in acc.items()}
    return date, big, full


class TdccQuery:
    """集保網站「股權分散表查詢」：查單一股票某一週的千張大戶持股比例（開放資料只有最新一週時才用）。"""
    URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"

    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.weeks = []

    def _token(self):
        html = decode(fetch(self.URL, opener=self.opener, retries=3))
        self.weeks = re.findall(r'<option[^>]*value="(\d{8})"', html)
        m = re.search(r'name="SYNCHRONIZER_TOKEN"[^>]*value="([^"]+)"', html)
        if not m:
            raise FetchError("找不到集保查詢表單的 token")
        return m.group(1)

    def available_weeks(self):
        if not self.weeks:
            self._token()
        return self.weeks

    def big_pct(self, code, week):
        tok = self._token()
        form = {"SYNCHRONIZER_TOKEN": tok, "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock", "method": "submit",
                "firDate": self.weeks[0] if self.weeks else week, "scaDate": week, "sqlMethod": "StockNo",
                "stockNo": code, "stockName": ""}
        html = decode(fetch(self.URL, data=form, opener=self.opener, retries=3))
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S):
            cells = [re.sub(r"<[^>]+>|&nbsp;", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
            if len(cells) >= 5 and cells[0] == "15":
                return num(cells[4])
        return None


INDUSTRY = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織", "05": "電機機械", "06": "電器電纜",
    "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵", "11": "橡膠", "12": "汽車", "14": "建材營造",
    "15": "航運", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他",
    "21": "化學", "22": "生技醫療", "23": "油電燃氣", "24": "半導體", "25": "電腦週邊",
    "26": "光電", "27": "通信網路", "28": "電子零組件", "29": "電子通路", "30": "資訊服務",
    "31": "其他電子", "32": "文化創意", "33": "農業科技", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "91": "存託憑證",
}


def taipei_now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
