"""檢查下載的每日資料：有沒有漏掉的平日、哪些來源沒抓到。用法：python check_raw.py bt/raw 起日 迄日"""
import datetime as dt
import gzip
import json
import os
import sys
from collections import Counter

raw, a, b = sys.argv[1], dt.date.fromisoformat(sys.argv[2]), dt.date.fromisoformat(sys.argv[3])
missing, closed, ok, pend = [], [], 0, Counter()
pend_days = {}
d = a
while d <= b:
    if d.weekday() < 5:
        p, c = os.path.join(raw, f"{d}.json.gz"), os.path.join(raw, f"{d}.closed")
        if os.path.exists(p):
            ok += 1
            ex = json.load(gzip.open(p, "rt", encoding="utf-8"))
            for s in ex.get("pending", []):
                pend[s] += 1
                pend_days.setdefault(s, []).append(str(d))
        elif os.path.exists(c):
            closed.append(str(d))
        else:
            missing.append(str(d))
    d += dt.timedelta(days=1)
print(f"交易日 {ok}，休市 {len(closed)}，漏掉 {len(missing)}")
if missing:
    print("漏掉：", " ".join(missing))
print("休市：", " ".join(closed))
print("缺來源：", dict(pend))
for s, ds in pend_days.items():
    print(" ", s, ds[:12], "..." if len(ds) > 12 else "")
