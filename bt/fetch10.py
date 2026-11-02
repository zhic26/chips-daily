"""十年回測用：同 fetch.py，但任何錯誤都不中斷整段下載（格式看不懂的日子記成 .err，事後檢查）。
用法：python bt/fetch10.py 起日 迄日"""
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from chips import store  # noqa: E402
from chips import daily as D  # noqa: E402
from chips.daily import fetch_day  # noqa: E402
from chips.net import FetchError  # noqa: E402

OUT = "bt/raw"

# 舊日期有些來源格式不同（例如櫃買法人 2018 年以前）：單一來源看不懂就跳過，其他來源照存
_orig_run = D._run


def _safe_run(src, d, ex, companies):
    try:
        return _orig_run(src, d, ex, companies)
    except FetchError:
        raise
    except Exception as e:  # noqa: BLE001
        print(d, src, "格式看不懂，略過：", repr(e)[:200], flush=True)
        return False


D._run = _safe_run


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


def commit(tag):
    git("add", OUT)
    if git("commit", "-qm", f"回測資料 {tag}").returncode != 0:
        return
    for i in range(8):
        git("pull", "-q", "--rebase", "origin", "backtest")
        if git("push", "-q", "origin", "HEAD:backtest").returncode == 0:
            print("已存回分支", tag, flush=True)
            return
        time.sleep(5 + 7 * i)
    print("推送失敗", tag, flush=True)


def main():
    start, end = (dt.date.fromisoformat(x) for x in sys.argv[1:3])
    comp = (store.load_meta("companies") or {}).get("data", {})
    os.makedirs(OUT, exist_ok=True)
    d, n, t0, pending_commit = start, 0, time.time(), 0
    while d <= end:
        if d.weekday() < 5:
            path, closed = f"{OUT}/{d}.json.gz", f"{OUT}/{d}.closed"
            if not (os.path.exists(path) or os.path.exists(closed)):
                ex = "ERR"
                for attempt in range(4):
                    try:
                        ex = fetch_day(d, comp)
                        break
                    except FetchError as e:
                        print(d, "連線失敗，一分鐘後重試：", e, flush=True)
                        time.sleep(60)
                    except Exception as e:  # noqa: BLE001  舊日期格式不同：記下來，不中斷
                        print(d, "格式錯誤：", repr(e)[:300], flush=True)
                        with open(f"{OUT}/{d}.err", "w") as fh:
                            fh.write(repr(e)[:2000])
                        pending_commit += 1
                        break
                if ex is None:
                    open(closed, "w").close()
                    print(d, "休市", flush=True)
                elif ex != "ERR":
                    ex.pop("shares", None)
                    with gzip.open(path, "wt", encoding="utf-8") as f:
                        json.dump(ex, f, ensure_ascii=False, separators=(",", ":"))
                    n += 1
                    pending_commit += 1
                    print(d, "完成", "缺：" + ",".join(ex["pending"]) if ex["pending"] else "",
                          f"平均 {(time.time() - t0) / n:.1f} 秒/日", flush=True)
            if pending_commit >= 20:
                commit(str(d))
                pending_commit = 0
        d += dt.timedelta(days=1)
    commit(f"{start}~{end} 完成")


if __name__ == "__main__":
    main()
