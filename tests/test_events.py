"""最近公布的結果：聯準會聲明、勞工統計局的 CPI 與非農、市場反應、每種留最近一次、存起來之後不重抓。"""
import datetime as dt
import tempfile
import unittest
from zoneinfo import ZoneInfo

from chips import events as E
from chips import macro as M
from chips import store
from chips.checks import DataError
from chips.net import FetchError

TPE = ZoneInfo("Asia/Taipei")

# 照 2026/10/28 聲明的寫法（其他段落省略）；meta、script 裡的字不能被當成內文
HOLD = """<html><head><meta name="description" content="decided to raise ... by a 9 – 3 vote">
<script>var s = "decided to lower the target range for the federal funds rate by 1/2 percentage point to 1 to 1-1/4 percent";</script></head>
<body><h3>Federal Reserve issues FOMC statement</h3><p>October 28, 2026</p>
<p>The Federal Open Market Committee approved the following statement for release by a 10 &ndash; 2 vote:</p>
<p>（其他段落省略）The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4&nbsp;percent, （省略）</p>
<p>Voting against the monetary policy action were Lisa D. Cook and Beth M. Hammack, who preferred to raise the target range
for the federal funds rate by 1/4 percentage point at this meeting.</p>
<p>For media inquiries, please email media@frb.gov.</p></body></html>"""

RAISE = """<p>The Federal Open Market Committee approved the following statement for release by a 12 – 0 vote:</p>
<p>The Committee decided to raise the target range for the federal funds rate by 1/4 percentage point to 3-3/4 to 4 percent</p>"""

# 反對的人主張不一樣（舊寫法，沒有「by a 9 – 3 vote」那句）
MIXED = """<p>the Committee decided to lower the target range for the federal funds rate by 1/4 percentage point to 3-1/2 to 3-3/4 percent.</p>
<p>Voting for the monetary policy action were Jerome H. Powell, Chair; John C. Williams, Vice Chair; and Christopher J. Waller.
Voting against this action were Stephen I. Miran, who preferred to lower the target range for the federal funds rate by 1/2
percentage point at this meeting; and Austan D. Goolsbee and Jeffrey R. Schmid, who preferred no change to the target range
for the federal funds rate at this meeting.</p>"""


def bls(series):
    """勞工統計局 API 回應的樣子（新的月份在前，數字是字串）。"""
    return {"status": "REQUEST_SUCCEEDED", "responseTime": 120, "message": [], "Results": {"series": [
        {"seriesID": sid, "data": [{"year": ym[:4], "period": "M" + ym[5:] if len(ym) > 4 else "M13", "periodName": "",
                                    "value": str(v), "footnotes": [{}]} for ym, v in reversed(rows)]}
        for sid, rows in series.items()]}}


# 數字是編的，只是讓年增率剛好等於 9 月官方公布的 3.7%（8 月 3.4%）、核心 2.6%（2.4%）
NSA = [("2025-08", 100.0), ("2025-09", 100.0), ("2025-10", "-"), ("2025", 100.0), ("2026-08", 103.4), ("2026-09", 103.7)]
CORE = [("2025-08", 200.0), ("2025-09", 200.0), ("2026-08", 204.8), ("2026-09", 205.2)]
PAY = [("2026-07", 159000), ("2026-08", 159133), ("2026-09", 159162)]
UR = [("2026-08", 4.1), ("2026-09", 4.2)]
BLS = {"CUUR0000SA0": NSA, "CUUR0000SA0L1E": CORE, "CES0000000001": PAY, "LNS14000000": UR}


def one(sid, rows):
    return E.parse_bls(bls({sid: rows}))[sid]


def ev(fomc=(), manual=()):
    return M.timeline([{"date": d, "sep": False} for d in fomc], list(manual))


CBC = {"date": "2026-09-17", "kind": "cbc", "name": "台灣央行理監事會", "result": "利率不變（重貼現率 2%）"}
NFP = {"date": "2026-10-02", "time": "08:30", "tz": "America/New_York", "kind": "nfp", "name": "美國非農就業（9 月）"}
CPI = {"date": "2026-10-14", "time": "08:30", "tz": "America/New_York", "kind": "cpi", "name": "美國 CPI（9 月）"}
ELECTION = {"date": "2026-11-03", "kind": "election", "name": "美國期中選舉"}
SPX = [("2026-10-01", 100.0), ("2026-10-02", 101.0), ("2026-10-13", 100.0), ("2026-10-14", 98.5),
       ("2026-10-27", 100.0), ("2026-10-28", 100.28), ("2026-11-03", 100.0), ("2026-11-04", 102.0)]
TNX = [("2026-10-27", 4.80), ("2026-10-28", 4.852)]
TAIEX = {"2026-09-17": 0.96, "2026-09-18": 1.93, "2026-10-02": 0.25, "2026-10-05": 2.55, "2026-10-15": -3.41,
         "2026-10-29": -1.42, "2026-10-30": -2.0, "2026-11-04": 0.1, "2026-11-05": 0.3}


class Fed(unittest.TestCase):
    def test_frac(self):
        self.assertEqual([E._frac(x) for x in ("3-3/4", "4", "1/4", "0", "4-1/2")], [3.75, 4, 0.25, 0, 4.5])
        with self.assertRaises(DataError):
            E._frac("3.75")

    def test_hold_with_dissent(self):
        r = E.parse_fed(HOLD)
        self.assertEqual((r["way"], r["lo"], r["hi"], r["for"], r["against"]), ("hold", 3.75, 4, 10, 2))
        self.assertEqual(r["dissent"], [{"n": 2, "way": "raise", "by": 0.25}])
        self.assertEqual(E.fed_text(r), "維持 3.75%～4.00% 不變（10 比 2，反對的 2 位主張升 1 碼）")

    def test_raise_unanimous(self):
        r = E.parse_fed(RAISE)
        self.assertEqual(E.fed_text(r), "升息 1 碼到 3.75%～4.00%（12 比 0 全票通過）")

    def test_mixed_dissent(self):
        r = E.parse_fed(MIXED)
        self.assertEqual(r["dissent"], [{"n": 1, "way": "lower", "by": 0.5}, {"n": 2, "way": "hold", "by": None}])
        self.assertEqual(E.fed_text(r), "降息 1 碼到 3.50%～3.75%（反對的 3 位：1 位主張降 2 碼、2 位主張不動）")

    def test_changed_page(self):
        with self.assertRaises(DataError):
            E.parse_fed("<p>The Committee will hold a press conference.</p>")


class Bls(unittest.TestCase):
    def test_parse(self):
        s = E.parse_bls(bls({"CUUR0000SA0": NSA}))["CUUR0000SA0"]
        self.assertEqual(s["2026-09"], 103.7)
        self.assertNotIn("2025-10", s)  # 缺值「-」跳過
        self.assertEqual(len(s), 4)     # M13（全年平均）不要
        with self.assertRaises(FetchError):  # 超過每天的次數上限：下次再試，不算改版
            E.parse_bls({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"], "Results": {}})
        with self.assertRaises(DataError):
            E.parse_bls({"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "X", "data": []}]}})

    def test_round_half_up(self):
        self.assertEqual((E._r1(3.65), E._r1(3.6499), E._r1(-0.05)), (3.7, 3.6, -0.1))
        self.assertEqual((E._sg(2.555, 2), E._sg(-0.004, 2), E._sg(0.052, 2)), ("+2.56", "0.00", "+0.05"))

    def test_ref_month(self):
        self.assertEqual(E.ref_month(CPI), "2026-09")
        self.assertEqual(E.ref_month({"date": "2027-01-13", "name": "美國 CPI（12 月）"}), "2026-12")
        self.assertEqual(E.ref_month({"date": "2027-03-05", "name": "其他"}), "2027-02")

    def test_cpi(self):
        r = E.cpi_result(one("A", NSA), one("B", CORE), "2026-09")
        self.assertEqual((r["yoy"], r["prev"], r["core"], r["corePrev"]), (3.7, 3.4, 2.6, 2.4))
        self.assertEqual(E.cpi_text(r), "年增 3.7%（前月 3.4%），扣掉食物和能源的核心 2.6%（前月 2.4%）")
        self.assertIsNone(E.cpi_result(one("A", NSA), one("B", CORE), "2026-10"))  # 還沒公布

    def test_nfp(self):
        r = E.nfp_result(one("A", PAY), one("B", UR), "2026-09")
        self.assertEqual(E.nfp_text(r), "新增 2.9 萬人（前月 13.3 萬），失業率 4.2%（前月 4.1%）")
        self.assertEqual(E.nfp_text(dict(r, chg=-10, prev=-5)), "減少 1.0 萬人（前月 −0.5 萬），失業率 4.2%（前月 4.1%）")
        self.assertIsNone(E.nfp_result(one("A", PAY), one("B", UR), "2026-10"))


class Reaction(unittest.TestCase):
    def one(self, e):
        return E.reaction(e, SPX, TNX, TAIEX)

    def test_fed(self):
        """美東 10/28 下午 2 點（台北 10/29 凌晨 2 點）→ 當晚美股是 10/28，接著的台股是 10/29。"""
        e = ev(fomc=["2026-10-28"])[0]
        r = self.one(e)
        self.assertEqual(r, {"us": "2026-10-28", "spx": 0.28, "tnx": 0.052, "tw": "2026-10-29", "taiex": -1.42})
        self.assertEqual(E.react_text(e, r), "當晚美股 S&P 500 +0.28%、10 年債殖利率 +0.05 個百分點；台股 10/29 −1.42%")

    def test_friday_and_cbc(self):
        nfp, cbc = ev(manual=[NFP])[0], ev(manual=[CBC])[0]
        self.assertEqual(self.one(nfp)["tw"], "2026-10-05")  # 週五晚上公布 → 下週一的台股
        self.assertNotIn("tnx", self.one(nfp))  # 那天沒有殖利率資料就不寫
        self.assertEqual(self.one(cbc), {"tw": "2026-09-18", "taiex": 1.93})  # 台灣央行收盤後公布，只看隔天台股
        self.assertEqual(E.react_text(cbc, self.one(cbc)), "台股 9/18 +1.93%")

    def test_election(self):
        e = ev(manual=[ELECTION])[0]
        r = self.one(e)
        self.assertEqual((r["us"], r["tw"]), ("2026-11-04", "2026-11-05"))
        self.assertEqual(E.react_text(e, r), "美股 11/4 S&P 500 +2.00%；台股 11/5 +0.30%")

    def test_not_closed_yet(self):
        e = ev(fomc=["2026-10-28"])[0]
        r = E.reaction(e, SPX[:5], None, {"2026-10-28": 2.04})
        self.assertEqual(r, {})  # 美股還沒收盤、台股也還沒開


class Pick(unittest.TestCase):
    def test_latest_per_kind(self):
        tl = ev(fomc=["2026-09-16", "2026-10-28", "2026-12-09"],
                manual=[CBC, NFP, CPI, ELECTION, dict(CPI, date="2026-11-10", name="美國 CPI（10 月）")])
        now = dt.datetime(2026, 11, 5, 8, 0, tzinfo=TPE)
        self.assertEqual([(e["kind"], e["date"]) for e in E.pick(now, tl)],
                         [("election", "2026-11-03"), ("fomc", "2026-10-28"), ("cpi", "2026-10-14"),
                          ("nfp", "2026-10-02"), ("cbc", "2026-09-17")])
        later = dt.datetime(2026, 12, 15, 8, 0, tzinfo=TPE)  # 選舉過了 30 天就不留；Fed、CPI 換成新的一次
        self.assertEqual([(e["kind"], e["date"]) for e in E.pick(later, tl)],
                         [("fomc", "2026-12-09"), ("cpi", "2026-11-10"), ("nfp", "2026-10-02"), ("cbc", "2026-09-17")])

    def test_upcoming_drops_past(self):
        now = dt.datetime(2026, 10, 29, 6, 30, tzinfo=TPE)
        up = M.upcoming(now, [{"date": "2026-10-28", "sep": False}, {"date": "2026-12-09", "sep": True}], [ELECTION], days=60)
        self.assertEqual([e["name"] for e in up], ["美國期中選舉", "Fed 利率決策"])  # 10/29 凌晨 2 點那場已經過了


class Update(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.meta, store.META = store.META, self.tmp.name
        self.calls = []
        self.tl = ev(fomc=["2026-10-28"], manual=[CBC, NFP, CPI])
        self.now = dt.datetime(2026, 11, 2, 7, 0, tzinfo=TPE)

    def tearDown(self):
        store.META = self.meta
        self.tmp.cleanup()

    def web(self, url):
        self.calls.append(url)
        if "monetary20261028a" in url:
            return HOLD
        raise FetchError("404 " + url)

    def api(self, url, payload):
        self.calls.append(url)
        self.payload = payload
        return bls({k: v for k, v in BLS.items() if k in payload["seriesid"]})

    def run_once(self, fetch=None, problems=None, post=None):
        return E.update(self.now, self.tl, {"spx": SPX, "tnx": TNX}, TAIEX, fetch or self.web, problems, post or self.api)

    def test_results_and_cache(self):
        out = self.run_once()
        self.assertEqual([x["kind"] for x in out], ["fomc", "cpi", "nfp", "cbc"])
        fomc, cpi, nfp, cbc = out
        self.assertEqual(fomc["result"], "維持 3.75%～4.00% 不變（10 比 2，反對的 2 位主張升 1 碼）")
        self.assertEqual(fomc["react"], "當晚美股 S&P 500 +0.28%、10 年債殖利率 +0.05 個百分點；台股 10/29 −1.42%")
        self.assertEqual(fomc["at"], "2026-10-29T02:00+08:00")
        self.assertEqual(cpi["result"], "年增 3.7%（前月 3.4%），扣掉食物和能源的核心 2.6%（前月 2.4%）")
        self.assertEqual(cpi["react"], "當晚美股 S&P 500 −1.50%；台股 10/15 −3.41%")
        self.assertEqual(nfp["result"], "新增 2.9 萬人（前月 13.3 萬），失業率 4.2%（前月 4.1%）")
        self.assertEqual(cbc, {"at": "2026-09-17T23:59+08:00", "hasTime": False, "name": "台灣央行理監事會", "kind": "cbc",
                               "result": "利率不變（重貼現率 2%）", "react": "台股 9/18 +1.93%"})
        self.assertEqual(len(self.calls), 2)  # 聲明 1 次；CPI、非農的 4 個數列一次請求拿齊
        self.assertEqual(self.payload, {"seriesid": ["CES0000000001", "CUUR0000SA0", "CUUR0000SA0L1E", "LNS14000000"],
                                        "startyear": "2024", "endyear": "2026"})
        saved = store.load_meta("event_results")
        self.assertTrue(all(v["react"]["done"] for v in saved.values()))
        again = E.update(self.now + dt.timedelta(days=1), self.tl, {}, {}, self.web, None, self.api)  # 這次 Yahoo、台股都沒資料
        self.assertEqual(again, out)  # 存起來的結果和反應照用
        self.assertEqual(len(self.calls), 2)  # 不再重抓

    def test_not_yet(self):
        def down(url, payload=None):
            raise FetchError("timeout")
        out = self.run_once(down, post=down)
        self.assertEqual([x.get("pending") for x in out[:3]], ["結果還沒抓到，下次更新會再試。"] * 3)
        self.assertNotIn("res", store.load_meta("event_results")["fomc:2026-10-28"])
        out = self.run_once()  # 下次抓到了
        self.assertTrue(all("result" in x for x in out))

    def test_month_not_out_yet(self):
        """公布時間過了，但 API 還沒有那個月的數字：先顯示還沒抓到，只問一次。"""
        early = {k: v[:-1] for k, v in BLS.items()}
        out = self.run_once(post=lambda u, p: bls(early))
        self.assertEqual(out[1]["pending"], "結果還沒抓到，下次更新會再試。")

    def test_changed_page(self):
        problems = []
        self.run_once(lambda u: "<p>改版了</p>", problems, lambda u, p: {"status": "REQUEST_SUCCEEDED", "Results": {}})
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("Fed 利率決策" in x for x in problems))
        self.assertTrue(any("勞工統計局" in x for x in problems))

    def test_partial_reaction_kept(self):
        """第一次只有台股，第二次 Yahoo 才有美股：兩次的合起來，齊了才不再算。"""
        E.update(self.now, self.tl, {}, TAIEX, self.web, None, self.api)
        r = store.load_meta("event_results")["fomc:2026-10-28"]["react"]
        self.assertEqual(r, {"tw": "2026-10-29", "taiex": -1.42})
        E.update(self.now, self.tl, {"spx": SPX, "tnx": TNX}, {}, self.web, None, self.api)
        r = store.load_meta("event_results")["fomc:2026-10-28"]["react"]
        self.assertEqual(r, {"tw": "2026-10-29", "taiex": -1.42, "us": "2026-10-28", "spx": 0.28, "tnx": 0.052, "done": True})


if __name__ == "__main__":
    unittest.main()
