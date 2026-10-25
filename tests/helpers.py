"""測試共用：用 tests/fixtures 裡存下的官方網站回應取代網路下載。"""
import contextlib
import copy
import glob
import json
import os

from chips import sources as S
from chips import store

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ROUTES = {
    "fund/T86": "twse_T86", "afterTrading/MI_INDEX": "twse_MI_INDEX", "marginTrading/MI_MARGN": "twse_MI_MARGN",
    "insti/dailyTrade": "tpex_insti", "afterTrading/otc": "tpex_otc", "margin/balance": "tpex_margin",
    "announcement/notice": "twse_notice", "announcement/punish": "twse_punish",
    "bulletin/attention": "tpex_attention", "bulletin/disposal": "tpex_disposal",
}


def fixture(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


@contextlib.contextmanager
def fake_web(edit=None):
    """S.get_json 改成讀樣本。edit(name, j) 可以在回傳前改內容（模擬網站改版）。"""
    real = S.get_json

    def get_json(url, **kw):
        for key, name in ROUTES.items():
            if key in url:
                j = copy.deepcopy(fixture(name))
                return edit(name, j) if edit else j
        raise AssertionError("測試沒有這個網址的樣本：" + url)

    S.get_json = get_json
    try:
        yield
    finally:
        S.get_json = real


def latest(kind):
    """repo 裡最新一份真實資料（data/daily 或 data/picks）；沒有就回傳 None。"""
    files = sorted(f for f in glob.glob(os.path.join(store.DATA, kind, "*.json")))
    if kind == "daily":
        files = [f for f in files if not json.load(open(f, encoding="utf-8")).get("light")]
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)
