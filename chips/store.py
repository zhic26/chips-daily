"""資料存放：data/ 底下的每日盤後資料、集保週資料、每日選股結果。全部是 JSON，方便在 GitHub 上直接看。"""
import datetime as dt
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DAILY = os.path.join(DATA, "daily")      # 每個交易日的盤後資料（精簡版）
TDCC = os.path.join(DATA, "tdcc")        # 集保千張大戶持股，每週一個檔
TDCCQ = os.path.join(DATA, "tdcc_query")  # 集保網站逐檔查詢的結果（補舊週資料用）
PICKS = os.path.join(DATA, "picks")      # 每日選股與排行結果
META = os.path.join(DATA, "meta")        # 公司基本資料、非交易日紀錄
for _p in (DAILY, TDCC, TDCCQ, PICKS, META):
    os.makedirs(_p, exist_ok=True)


def _read(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, obj, pretty=False):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        else:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, path)


def iso(d):
    return d.isoformat() if isinstance(d, dt.date) else str(d)


# ---- 每日盤後資料 ----

def daily_path(d):
    return os.path.join(DAILY, f"{iso(d)}.json")


def load_daily(d):
    return _read(daily_path(d))


def save_daily(d, obj):
    _write(daily_path(d), obj)


def daily_dates():
    """已存下的交易日（新到舊）。"""
    names = [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(DAILY, "*.json"))]
    return sorted((dt.date.fromisoformat(n) for n in names), reverse=True)


def prune_daily(keep):
    for d in daily_dates()[keep:]:
        os.remove(daily_path(d))


# ---- 集保 ----

def save_tdcc(week, big):
    path = os.path.join(TDCC, f"{week}.json")
    if not os.path.exists(path):
        _write(path, {"week": week, "big1000": big})
        return True
    return False


def tdcc_weeks():
    return sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(TDCC, "*.json")))


def load_tdcc(week):
    j = _read(os.path.join(TDCC, f"{week}.json"))
    return (j or {}).get("big1000")


def load_tdcc_query(week):
    return _read(os.path.join(TDCCQ, f"{week}.json"), {})


def save_tdcc_query(week, data):
    _write(os.path.join(TDCCQ, f"{week}.json"), data)


# ---- 選股結果 ----

def picks_path(d):
    return os.path.join(PICKS, f"{iso(d)}.json")


def load_picks(d):
    return _read(picks_path(d))


def save_picks(d, obj):
    _write(picks_path(d), obj, pretty=True)


def picks_dates():
    names = [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(PICKS, "*.json"))]
    return sorted((dt.date.fromisoformat(n) for n in names), reverse=True)


# ---- 其他 ----

def load_meta(name, default=None):
    return _read(os.path.join(META, f"{name}.json"), default)


def save_meta(name, obj):
    _write(os.path.join(META, f"{name}.json"), obj, pretty=True)


def meta_age_days(name):
    path = os.path.join(META, f"{name}.json")
    if not os.path.exists(path):
        return None
    j = _read(path, {})
    try:
        saved = dt.date.fromisoformat(j.get("_saved", ""))
    except ValueError:
        return None
    return (dt.date.today() - saved).days


def load_config():
    return _read(os.path.join(ROOT, "config.json"), {})
