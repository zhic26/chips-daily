"""把 bt8/out 的第 8 版回測結果寫進網站的 config.json（backtest、exit.backtest、exit.slots）。先印出新舊數字對照。"""
import csv
import json
import sys

import pandas as pd

SITE = "/home/claude/chips-daily/config.json"
O = "out"
s3 = json.load(open(f"{O}/site_numbers3.json", encoding="utf-8"))
sn = json.load(open(f"{O}/site_numbers.json", encoding="utf-8"))
rs = json.load(open(f"{O}/rank_split.json", encoding="utf-8"))
so = json.load(open(f"{O}/solutions.json", encoding="utf-8"))
lr = {r["規則"]: r for r in csv.DictReader(open(f"{O}/long_rules.csv", encoding="utf-8"))}
tr = pd.read_pickle(f"{O}/long_trades.pkl")
cfg = json.load(open(SITE, encoding="utf-8"))
old = json.loads(json.dumps(cfg))
B, E, SL = cfg["backtest"], cfg["exit"]["backtest"], cfg["exit"]["slots"]


def dd(d):
    return {m: {"d5": d[m]["d5"], "d20": d[m]["d20"]} for m in ("上市", "上櫃")}


def bb(key):
    x = s3["by_breadth"][key]
    return {"d5": x["d5"], "d20": x["d20"]}


# ---------- backtest（名單 5／20 日超額） ----------
B["old"] = {"model": 7, "overall": dd({m: old["backtest"]["overall"][m] for m in ("上市", "上櫃")})}
B["model"] = 8
B["period"] = s3["period"]
B["days"] = s3["days"]
B["overall"] = dd(s3["overall"])
B["by_breadth"] = {"上市": bb("上市 全期"), "上櫃": bb("上櫃 全期")}
B["recent"]["days"] = s3["recent"]["上市"]["n5"]
B["recent"]["overall"] = dd(s3["recent"])
B["recent"]["by_breadth"] = {"上市": bb("上市 2024/10 以後"), "上櫃": bb("上櫃 2024/10 以後")}
by = s3["by_year"]
neg = {m: [(y, v[m]["d20"]) for y, v in by.items() if v.get(m) and v[m]["d20"] < 0] for m in ("上市", "上櫃")}
print("負的年份", neg)
bef = s3["before"]

# ---------- exit.backtest（參考賣法） ----------
E["model"] = 8
E["trades"] = len(tr)  # 實際成交的筆數（扣掉開盤鎖漲停買不到的），跟第 7 版一樣用 long_check 的數字
E["rule"] = sn["rule"]
E["hold20"] = {k: v for k, v in sn["hold20"].items() if k != "full"}
h60 = lr["固定抱 60 天"]
E["hold60"] = {"per20": float(h60["每20日淨%"]), "excess20": float(h60["每20日超額%"])}
t10, t11 = rs["現行規則每20日"]["1-10"], rs["現行規則每20日"]["11-20"]
E["top10"] = {"_note": f"2026-11-10 第 8 版：同一批 12 年交易只算每份名單的前 10 名（backtest 分支 bt/analysis/v8/rank_split.py）；第 11～20 名是 {t11['淨']}、{t11['超額']}、{t11['勝率']}%",
              "per20": t10["淨"], "excess20": t10["超額"], "win": t10["勝率"], "trades": t10["筆數"]}
rc = tr[tr.date >= "2024-10-01"]
per = lambda d, c: round(float(d[c].mean() / d.days.mean() * 20 * 100), 2)  # noqa: E731
E["recent"] = {"period": f"2024/10～{tr.date.max().year}/{tr.date.max().month}", "per20": per(rc, "net"), "excess20": per(rc, "exc")}
pr = list(sn["price"].values())
E["price"]["range"] = f"{min(pr):.1f}%～{max(pr):.1f}%（現在的規則是 {sn['rule']['per20']:.1f}%）"
l40, l150 = lr["跌出前 40 名就賣"], lr["跌出前 150 名就賣"]
print("跌出前 40 名", l40, "前 150 名", l150)

# ---------- exit.slots（帳戶模擬） ----------
SL["k"] = {}
for K, o in sn["slots"].items():
    SL["k"][K] = {"daily": o["daily"], "weekly": o["weekly"], "rand": o["rand"], "randDD": o["randDD"], "lose": o["lose"]}
SL["taiex"]["cagr"], SL["taiex"]["mdd"] = sn["taiex"][0], sn["taiex"][1]
SL["taiex"]["dd"] = sn["taiex"][2:]
f = SL["filter"]
w_, n_, i_ = so["小資版＋濾網：站上季線 >50%"], so["小資版 1 檔（對照）"], so["加權定期定額"]
f["with"] = [w_["irr"], w_["mdd"], w_["mult"]]
f["without"] = [n_["irr"], n_["mdd"], n_["mult"]]
f["index"] = [i_["irr"], i_["mdd"], i_["mult"]]
f["months"] = [int(x) for x in w_["月份用名單"].split("/")]

print(json.dumps({"backtest": {k: B[k] for k in ("overall", "old", "by_breadth", "recent")}, "before": bef}, ensure_ascii=False))
print(json.dumps({k: E[k] for k in ("trades", "rule", "hold20", "hold60", "top10", "recent", "price")}, ensure_ascii=False))
print(json.dumps({"k": SL["k"], "filter": {k: f[k] for k in ("with", "without", "index", "months")}, "taiex": SL["taiex"]}, ensure_ascii=False))
if "--write" in sys.argv:
    json.dump(cfg, open(SITE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已寫入", SITE)
