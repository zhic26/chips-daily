"""國際盤勢：Yahoo 走勢圖的解析（去掉週末和還沒收盤的那根）、央行的台北收盤匯率、ADR 溢價、聯準會會議日程、事件時間換算、文字說明。"""
import datetime as dt
import json
import os
import re
import tempfile
import unittest
from zoneinfo import ZoneInfo

from chips import macro as M
from chips import store
from chips.checks import DataError
from chips.net import FetchError
from tests.helpers import FIX

TPE = dt.timezone(dt.timedelta(hours=8))
NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")


def chart(name):
    with open(os.path.join(FIX, "macro", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def cbc_page(until=None):
    """央行收盤匯率頁的樣本（2026/11/12 下午抓的，60 筆：8/14～11/12）。until：只留這天（含）以前的列。"""
    with open(os.path.join(FIX, "macro", "cbc_twd.html"), encoding="utf-8") as f:
        html = f.read()
    if until:
        html = re.sub(r"<tr>\s*<td[^>]*><span>(\d{4})/(\d{2})/(\d{2})</span></td>.*?</tr>",
                      lambda m: m.group(0) if "-".join(m.groups()) <= until else "", html, flags=re.S)
    return html


class Chart(unittest.TestCase):
    def test_after_close(self):
        s = M.parse_chart(chart("SOX"), dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE).timestamp())
        self.assertEqual(s[-1][0], "2026-10-23")
        self.assertGreater(len(s), 100)
        self.assertEqual(len({d for d, _ in s}), len(s))

    def test_session_in_progress(self):
        """美股還在交易（台北時間晚上）時，最後一根還沒收盤，要去掉。"""
        reg = chart("SOX")["chart"]["result"][0]["meta"]["currentTradingPeriod"]["regular"]
        s = M.parse_chart(chart("SOX"), reg["start"] + 3600)
        self.assertEqual(s[-1][0], "2026-10-22")

    def test_weekend_and_fx(self):
        s = M.parse_chart(chart("TWD_X"), dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE).timestamp())
        self.assertEqual(s[-1][0], "2026-10-23")  # 週日的零星報價不算
        self.assertTrue(all(dt.date.fromisoformat(d).weekday() < 5 for d, _ in s))
        self.assertTrue(all(25 < v < 40 for _, v in s))

    def test_futures_and_rates(self):
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE).timestamp()
        self.assertEqual(M.parse_chart(chart("CL_F"), now)[-1][0], "2026-10-23")
        self.assertTrue(all(0.1 < v < 20 for _, v in M.parse_chart(chart("TNX"), now)))

    def test_broken(self):
        with self.assertRaises(DataError):
            M.parse_chart({"chart": {"result": None}}, 0)


class AllDay(unittest.TestCase):
    """期貨、美元指數、匯率幾乎 24 小時交易，Yahoo 的日線照當地日曆天切（到午夜才走完）。
    樣本是 2026/11/12 台北 16:32（紐約凌晨 3:32）抓的：最後一根是 11/12、還在跳動。"""

    def at(self, y, m, d, hh, mm, tz=NY):
        return dt.datetime(y, m, d, hh, mm, tzinfo=tz).timestamp()

    def test_day_session_not_over(self):
        s = M.parse_chart(chart("GC_F_live"), self.at(2026, 11, 12, 3, 32), all_day=True)
        self.assertEqual(s[-1], ("2026-11-11", 4000.5))  # 紐約的白天還沒開始：用前一天
        s = M.parse_chart(chart("GC_F_live"), self.at(2026, 11, 12, 16, 59), all_day=True)
        self.assertEqual(s[-1][0], "2026-11-11")  # 台北晚上那幾次更新（紐約早上）也一樣

    def test_taipei_morning_uses_last_night(self):
        """台北早上（紐約傍晚 5 點以後）：昨晚那根已經可以用了，不要等到紐約午夜。"""
        for hh, mm in ((17, 0), (18, 15), (19, 1), (23, 59)):
            s = M.parse_chart(chart("GC_F_live"), self.at(2026, 11, 12, hh, mm), all_day=True)
            self.assertEqual(s[-1][0], "2026-11-12", (hh, mm))
            self.assertAlmostEqual(s[-1][1], 3958.1, places=1)
            self.assertEqual(s[-2], ("2026-11-11", 4000.5))
        s = M.parse_chart(chart("DXY_live"), self.at(2026, 11, 12, 19, 1), all_day=True)
        self.assertEqual(s[-1][0], "2026-11-12")

    def test_old_rule_was_a_day_behind(self):
        """原本的判斷（照 Yahoo 的「交易時段」，期貨是整個日曆天）在台北早上會把昨晚那根丟掉。"""
        s = M.parse_chart(chart("GC_F_live"), self.at(2026, 11, 12, 19, 1))
        self.assertEqual(s[-1][0], "2026-11-11")

    def test_weekend(self):
        s = M.parse_chart(chart("GC_F_live"), self.at(2026, 11, 14, 10, 0), all_day=True)
        self.assertEqual(s[-1][0], "2026-11-12")  # 樣本只到 11/12；週末不會多丟一根
        s = M.parse_chart(chart("CL_F"), dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE).timestamp(), all_day=True)
        self.assertEqual(s[-1][0], "2026-10-23")

    def test_fx_follows_new_york_not_london_midnight(self):
        """新台幣的國際報價（算 ADR 溢價用）是倫敦的日曆天；一樣以紐約下午 5 點（倫敦晚上 10 點）為準。"""
        f = chart("TWD_X_live")
        s = M.parse_chart(f, self.at(2026, 11, 12, 8, 32, LONDON), all_day=True)
        self.assertEqual(s[-1][0], "2026-11-11")
        self.assertAlmostEqual(s[-1][1], 32.9538, places=4)
        self.assertEqual(M.parse_chart(f, self.at(2026, 11, 12, 21, 59, LONDON), all_day=True)[-1][0], "2026-11-11")
        self.assertEqual(M.parse_chart(f, self.at(2026, 11, 12, 23, 15, LONDON), all_day=True)[-1][0], "2026-11-12")  # 台北 07:15

    def test_stock_indices_unchanged(self):
        reg = chart("SOX")["chart"]["result"][0]["meta"]["currentTradingPeriod"]["regular"]
        self.assertEqual(M.parse_chart(chart("SOX"), reg["start"] + 3600)[-1][0], "2026-10-22")
        self.assertEqual(M.ALL_DAY, {"dxy", "usdtwd", "wti", "gold"})
        self.assertFalse(M.ALL_DAY & {"sox", "ixic", "spx", "tsm", "vix", "tnx"})


class Cbc(unittest.TestCase):
    """新台幣：中央銀行公布的台北銀行間收盤匯率。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.meta, store.META = store.META, self.tmp.name

    def tearDown(self):
        store.META = self.meta
        self.tmp.cleanup()

    def test_parse(self):
        s = M.parse_cbc(cbc_page())
        self.assertEqual(len(s), 60)
        self.assertEqual((s[0], s[-1]), (("2026-08-14", 32.046), ("2026-11-12", 32.889)))
        d = dict(s)
        # 跟報紙寫的台北收盤一樣（Yahoo 那幾天是 33.11、32.76、32.79、32.95，方向全相反）
        self.assertEqual([d[x] for x in ("2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11")],
                         [32.876, 32.768, 32.882, 32.865, 32.86])
        self.assertNotIn("2026-10-23", d)  # 那天台北沒有交易
        self.assertEqual([x for x, _ in s], sorted(x for x, _ in s))

    def test_changed_page(self):
        with self.assertRaises(DataError):
            M.parse_cbc("<html><table><tr><td>2026/11/12</td><td>32.889</td></tr></table></html>")  # 沒有 NTD/USD 欄
        with self.assertRaises(DataError):
            M.parse_cbc(cbc_page(until="2026-08-20"))  # 只剩幾筆
        with self.assertRaises(DataError):
            M.parse_cbc(cbc_page().replace("<td data-th=\"NTD/USD\">", "<td>改版</td><td>"))  # 一列變成三格

    def test_store_accumulates(self):
        s1 = M.taipei_twd(lambda u: cbc_page(until="2026-11-10"))
        self.assertEqual(s1[-1], ("2026-11-10", 32.865))
        self.assertEqual(len(s1), 58)

        def only_recent(url):  # 哪天網頁只給最近 20 筆
            self.assertEqual(url, M.CBC_URL)
            page = cbc_page()
            keep = set(re.findall(r"<span>(\d{4}/\d{2}/\d{2})</span>", page)[:20])
            return re.sub(r"<tr>\s*<td[^>]*><span>(\d{4}/\d{2}/\d{2})</span></td>.*?</tr>",
                          lambda m: m.group(0) if m.group(1) in keep else "", page, flags=re.S)
        s2 = M.taipei_twd(only_recent)
        self.assertEqual(len(s2), 60)  # 以前存的還在
        self.assertEqual(s2[-1], ("2026-11-12", 32.889))
        self.assertEqual(len(store.load_meta("twd")["rates"]), 60)

    def test_unreasonable_value(self):
        with self.assertRaises(DataError):
            M.taipei_twd(lambda u: cbc_page().replace("<span>32.889</span>", "<span>328.89</span>"))
        self.assertIsNone(store.load_meta("twd"))  # 不合理的數字不存

    def test_stats(self):
        s = [(f"2026-01-{i + 1:02d}", 100.0 + i) for i in range(60)]
        st = M.stats(s)
        self.assertEqual(st["last"], 159.0)
        self.assertAlmostEqual(st["chg1"], (159 / 158 - 1) * 100, places=2)
        self.assertAlmostEqual(st["chg20"], (159 / 139 - 1) * 100, places=2)
        self.assertEqual(st["d20"], 20.0)
        self.assertAlmostEqual(st["ma50"], (159 / (sum(range(110, 160)) / 50) - 1) * 100, places=2)
        self.assertEqual(len(st["spark"]), 60)


class Adr(unittest.TestCase):
    def test_premium(self):
        tsm = [("2026-10-21", 100.0), ("2026-10-22", 110.0)]
        twd = [("2026-10-20", 32.0)]
        tw = {"2026-10-21": 500.0, "2026-10-22": 500.0, "2026-10-23": 510.0}
        out = M.adr_premium(tsm, twd, tw)
        self.assertEqual([d for d, _ in out], ["2026-10-21", "2026-10-22"])  # 沒有 ADR 收盤的日子不算
        self.assertAlmostEqual(out[0][1], (100 / (500 * 5 / 32) - 1) * 100, places=2)


class Fomc(unittest.TestCase):
    def test_fixture(self):
        with open(os.path.join(FIX, "macro", "fomc.html"), encoding="utf-8") as f:
            m = M.parse_fomc(f.read())
        d = {x["date"]: x["sep"] for x in m}
        self.assertEqual(d.get("2026-10-28"), False)
        self.assertEqual(d.get("2026-12-09"), True)
        self.assertGreaterEqual(sum(1 for x in d if x.startswith("2026")), 8)

    def test_cross_month_and_notation(self):
        html = ('<h4>2027 FOMC Meetings</h4>'
                '<div class="fomc-meeting__month"><strong>Apr/May</strong></div><div class="fomc-meeting__date">30-1</div>'
                '<div class="fomc-meeting__month"><strong>August</strong></div><div class="fomc-meeting__date">22 (notation vote)</div>'
                '<div class="fomc-meeting__month"><strong>June</strong></div><div class="fomc-meeting__date">15-16*</div>')
        self.assertEqual(M.parse_fomc(html), [{"date": "2027-05-01", "sep": False}, {"date": "2027-06-16", "sep": True}])

    def test_changed_page(self):
        with self.assertRaises(DataError):
            M.parse_fomc("<html>改版了</html>")


class Events(unittest.TestCase):
    def test_taipei_time(self):
        now = dt.datetime(2026, 10, 26, 8, 0, tzinfo=TPE)
        fomc = [{"date": "2026-10-28", "sep": False}, {"date": "2026-12-09", "sep": True}]
        manual = [{"date": "2026-11-10", "time": "08:30", "tz": "America/New_York", "kind": "cpi", "name": "美國 CPI（10 月）"},
                  {"date": "2026-12-17", "kind": "cbc", "name": "台灣央行理監事會"},
                  {"date": "2026-10-01", "time": "08:30", "tz": "America/New_York", "kind": "cpi", "name": "已經過了"}]
        ev = M.upcoming(now, fomc, manual, days=60)
        self.assertEqual([e["at"] for e in ev], ["2026-10-29T02:00+08:00", "2026-11-10T21:30+08:00",
                                                 "2026-12-10T03:00+08:00", "2026-12-17T23:59+08:00"])
        self.assertEqual(ev[2]["kind"], "fomc_sep")
        self.assertFalse(ev[3]["hasTime"])

    def test_events_file(self):
        """repo 裡的 events.json 要讀得進來（日期、時區格式正確）。"""
        problems = []
        ev = M._manual(problems)
        self.assertEqual(problems, [])
        self.assertTrue(ev)


class Read(unittest.TestCase):
    def test_sentences(self):
        t = {"sox": {"date": "2026-10-23", "chg1": 1.23, "chg20": -5.0, "ma50": -2.0}, "ixic": {"chg1": -0.5}, "spx": {"chg1": 0.0},
             "vix": {"last": 31.0}, "tnx": {"last": 4.5, "d20": 0.25}, "twd": {"last": 32.6, "chg20": 1.5},
             "wti": {"chg5": 8.0}, "gold": {"chg5": 1.0}}
        s = "".join(M.read(t, [("2026-10-22", 10.0), ("2026-10-23", 14.0)]))
        for x in ("費半 +1.2%", "跌破 50 日均線", "恐慌", "上升 0.25 個百分點", "新台幣近 20 日貶值 1.5%", "原油近 5 個交易日大漲 8.0%", "溢價 14.0%",
                  "10 年債殖利率 4.500%", "台北收盤 1 美元兌 32.600 元"):
            self.assertIn(x, s)
        self.assertNotIn("黃金", s)

    def test_yield_not_rounded_up_to_five(self):
        s = "".join(M.read({"tnx": {"last": 4.998, "d20": -0.19}}, []))
        self.assertIn("4.998%", s)
        self.assertNotIn("5.00%", s)


class Update(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.meta, store.META = store.META, self.tmp.name
        store.save_meta("fomc", {"_saved": dt.date.today().isoformat(), "meetings": [{"date": "2026-10-28", "sep": False}]})

    def tearDown(self):
        store.META = self.meta
        self.tmp.cleanup()

    def fetch(self, url):
        name = {"%5ESOX": "SOX", "TSM": "TSM", "TWD%3DX": "TWD_X", "%5ETNX": "TNX", "CL%3DF": "CL_F", "%5EVIX": "SOX"}
        for k, v in name.items():
            if f"/chart/{k}?" in url:
                return chart(v)
        raise FetchError("404")

    def nonet(self, url, payload=None):  # 事件結果（聯準會、勞工統計局）在測試裡不連網
        raise FetchError("測試不連網")

    def text(self, url):  # 央行收盤匯率用樣本（只留測試當天以前的），其他（聯準會聲明）不連網
        if url == M.CBC_URL:
            return cbc_page(until="2026-10-23")
        raise FetchError("測試不連網")

    def test_update(self):
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE)
        m, problems = M.update(now, {"2026-10-22": 1465.0, "2026-10-21": 1480.0}, fetch_json=self.fetch, fetch_text=self.text, post_json=self.nonet)
        self.assertEqual(len(problems), 1)  # VIX 拿到費半的數字，超出合理範圍
        self.assertIn("VIX", problems[0])
        self.assertIn("那斯達克", m["missing"])
        self.assertNotIn("新台幣匯率", m["missing"])
        self.assertEqual(set(m["tiles"]), {"sox", "tsm", "twd", "tnx", "wti"})
        twd = m["tiles"]["twd"]  # 央行的台北收盤（10/23 那天台北沒有交易，最新是 10/22），不是 Yahoo 的國際報價
        self.assertEqual((twd["date"], twd["last"], twd["src"], twd["name"]), ("2026-10-22", 32.508, "cbc", "新台幣匯率"))
        self.assertAlmostEqual(twd["chg1"], (32.508 / 32.488 - 1) * 100, places=2)
        self.assertEqual(len(twd["spark"]), 47)  # 樣本裡 8/14～10/22 共 47 個交易日
        self.assertNotIn("usdtwd", m["tiles"])  # Yahoo 的報價不顯示，只拿來算 ADR 溢價
        self.assertEqual(m["aux"], {"usdtwd": "2026-10-23"})
        self.assertTrue(m["adr"])
        self.assertAlmostEqual(m["adr"][-1][1], (dict(M.parse_chart(chart("TSM"), now.timestamp()))["2026-10-22"]
                                                 / (1465.0 * 5 / 32.366) - 1) * 100, places=2)  # 32.366：Yahoo 10/22 的報價
        self.assertTrue(m["read"])
        self.assertEqual([e["kind"] for e in m["past"]], ["cpi", "nfp", "cbc"])  # 10/25 時已經過去的（Fed 10/28 還沒到）
        self.assertTrue(m["past"][2]["result"])  # 台灣央行的結果是 events.json 手寫的
        self.assertEqual(m["past"][0]["pending"], "結果還沒抓到，下次更新會再試。")
        later = now + dt.timedelta(hours=10)
        m2, _ = M.update(later, {"2026-10-22": 1465.0, "2026-10-21": 1480.0}, fetch_json=self.fetch, fetch_text=self.text, post_json=self.nonet)
        self.assertEqual(m2["asOf"], m["asOf"])  # 數字沒變，時間也不變（網頁不會多一次更新）

    def test_keeps_old_values(self):
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE)
        M.update(now, {}, fetch_json=self.fetch, fetch_text=self.text, post_json=self.nonet)

        def down(url):
            raise FetchError("timeout")
        m, problems = M.update(now + dt.timedelta(days=1), {}, fetch_json=down, fetch_text=self.nonet, post_json=self.nonet)
        self.assertEqual(problems, [])
        self.assertTrue(m["tiles"]["sox"]["stale"])
        self.assertTrue(m["tiles"]["twd"]["stale"])  # 央行網頁連不上：沿用上次的台北收盤並註明日期
        self.assertEqual((m["tiles"]["twd"]["date"], m["tiles"]["twd"]["src"]), ("2026-10-22", "cbc"))
        self.assertIn("新台幣匯率", m["missing"])
        self.assertEqual(m["aux"], {"usdtwd": "2026-10-23"})

    def test_twd_first_run_without_cbc(self):
        """第一次就連不上央行：沒有新台幣那一格（不拿 Yahoo 的國際報價頂替），ADR 溢價照算。"""
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE)
        m, problems = M.update(now, {"2026-10-22": 1465.0}, fetch_json=self.fetch, fetch_text=self.nonet, post_json=self.nonet)
        self.assertNotIn("twd", m["tiles"])
        self.assertIn("新台幣匯率", m["missing"])
        self.assertTrue(m["adr"])
        self.assertFalse([p for p in problems if "新台幣" in p])

    def test_twd_replaces_old_yahoo_tile(self):
        """改版前存的新台幣那一格是 Yahoo 的數字（日期可能比央行的新）：直接換成央行的，不當成「這次比較舊」。"""
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE)
        store.save_meta("macro", {"tiles": {"twd": {"date": "2026-10-23", "last": 32.597, "name": "新台幣匯率", "unit": "元"}},
                                  "asOf": "2026-10-25T08:00+08:00"})
        m, _ = M.update(now, {}, fetch_json=self.fetch, fetch_text=self.text, post_json=self.nonet)
        self.assertEqual((m["tiles"]["twd"]["date"], m["tiles"]["twd"]["last"], m["tiles"]["twd"]["src"]), ("2026-10-22", 32.508, "cbc"))

    def test_twd_changed_page_is_reported(self):
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE)

        def changed(url):
            if url == M.CBC_URL:
                return "<html>網站改版</html>"
            raise FetchError("測試不連網")
        m, problems = M.update(now, {}, fetch_json=self.fetch, fetch_text=changed, post_json=self.nonet)
        self.assertTrue([p for p in problems if "央行" in p])  # 格式不對要讓這次執行顯示失敗
        self.assertNotIn("twd", m["tiles"])

    def test_morning_run_shows_last_night(self):
        """早上那次更新：黃金、美元指數顯示昨晚的（原本會停在前一天）。樣本是 11/12 抓的，假裝現在是紐約 11/12 晚上 7 點。"""
        def fetch(url):
            for k, v in {"GC%3DF": "GC_F_live", "DX-Y.NYB": "DXY_live", "TWD%3DX": "TWD_X_live"}.items():
                if f"/chart/{k}?" in url:
                    j = chart(v)  # 樣本只有一個月（二十幾天），補成夠長的走勢
                    r = j["chart"]["result"][0]
                    q = r["indicators"]["quote"][0]
                    t0, n = r["timestamp"][0], 40
                    r["timestamp"] = [t0 - 86400 * (n - i) for i in range(n)] + r["timestamp"]  # 週末那幾根解析時會自己去掉
                    q["close"] = [q["close"][0]] * n + q["close"]
                    return j
            raise FetchError("404")
        now = dt.datetime(2026, 11, 12, 19, 1, tzinfo=NY).astimezone(TPE)
        m, _ = M.update(now, {}, fetch_json=fetch, fetch_text=lambda u: cbc_page(), post_json=self.nonet)
        self.assertEqual((m["tiles"]["gold"]["date"], m["tiles"]["dxy"]["date"]), ("2026-11-12", "2026-11-12"))
        self.assertAlmostEqual(m["tiles"]["gold"]["chg1"], (3958.1001 / 4000.5 - 1) * 100, places=2)
        self.assertEqual(m["aux"], {"usdtwd": "2026-11-12"})
        self.assertEqual((m["tiles"]["twd"]["date"], m["tiles"]["twd"]["last"]), ("2026-11-12", 32.889))

    def test_never_goes_back(self):
        """Yahoo 有時回傳少了最後一天的資料：不能拿比較舊的蓋掉已經有的，ADR 溢價也要沿用。"""
        now = dt.datetime(2026, 10, 25, 22, 0, tzinfo=TPE)
        closes = {"2026-10-22": 1465.0, "2026-10-21": 1480.0}
        m1, _ = M.update(now, closes, fetch_json=self.fetch, fetch_text=self.text, post_json=self.nonet)

        def short(url):
            j = self.fetch(url)
            if "/chart/TSM?" in url:
                j = json.loads(json.dumps(j))
                r = j["chart"]["result"][0]
                r["timestamp"] = r["timestamp"][:-1]
                q = r["indicators"]["quote"][0]
                for k in q:
                    q[k] = q[k][:-1]
            return j
        m2, problems = M.update(now + dt.timedelta(hours=1), closes, fetch_json=short, fetch_text=self.text, post_json=self.nonet)
        self.assertFalse([p for p in problems if "ADR" in p])  # 只剩測試資料故意放錯的 VIX
        self.assertEqual(m2["tiles"]["tsm"], m1["tiles"]["tsm"])
        self.assertNotIn("stale", m2["tiles"]["tsm"])
        self.assertNotIn("台積電 ADR", m2["missing"])
        self.assertEqual(m2["adr"], m1["adr"])


if __name__ == "__main__":
    unittest.main()
