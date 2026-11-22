"""驗證「VIX 接近 30 時買股票勝率相當高，彈到 40 時要輸錢真的很難」（Threads 說是股癌講的；2026-11-23 使用者要求）。
資料：bt/vix_hist（Yahoo 日線收盤：VIX 1990 起、S&P 500 1985 起、加權指數 1997/7 起），不含股息。
- 訊號：VIX 收盤 ≥ 門檻的每一天（會重疊），以及「新的一波」＝之前 21 個交易日都低於門檻、這天第一次收在門檻以上。
- 買進：S&P 500 當天收盤；加權指數用美國那天之後台灣下一個交易日的收盤（台股隔天早上才開）。
- 看 1、3、6、12 個月（21、63、126、252 個交易日）後的漲跌、上漲比例，以及買進後半年內最多再跌多少。
- 對照：所有日子。
在跟 bt-branch 同一層的資料夾執行：python3 vix_check.py → out/vix_check.json"""
import json
import os

import numpy as np
import pandas as pd

BT = "../bt-branch/bt"


def load(sym):
    s = pd.Series({d: c for d, c in json.load(open(f"{BT}/vix_hist/{sym}.json"))})
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


vix, spx, twii = load("VIX"), load("GSPC"), load("TWII")
H = {"1個月": 21, "3個月": 63, "6個月": 126, "12個月": 252}
r1 = lambda x: None if x is None or not np.isfinite(x) else round(float(x), 1)  # noqa: E731


def fwd(px):
    p = px.values
    out = {}
    for k, h in H.items():
        f = np.full(len(p), np.nan)
        f[:-h] = p[h:] / p[:-h] - 1
        out[k] = pd.Series(f, index=px.index)
    lo = np.full(len(p), np.nan)
    for i in range(len(p) - 1):
        lo[i] = p[i + 1:i + 127].min() / p[i] - 1
    out["半年內最多再跌"] = pd.Series(lo, index=px.index)
    return out


FS, FT = fwd(spx), fwd(twii)
v_on_spx = vix.reindex(spx.index).ffill()
# 加權：美國 t 日的訊號 → 台灣 t 之後的第一個交易日
tw_dates = twii.index


def tw_entry(d):
    k = tw_dates.searchsorted(d, side="right")
    return tw_dates[k] if k < len(tw_dates) else None


def stats(F, days):
    o = {"天數": int(len(days))}
    for k in list(H) + ["半年內最多再跌"]:
        x = F[k].reindex(days).dropna()
        if k == "半年內最多再跌":
            o["半年內最多再跌：中位數%"] = r1(x.median() * 100)
            o["半年內最多再跌：最糟%"] = r1(x.min() * 100)
        else:
            o[f"{k}：平均%"] = r1(x.mean() * 100)
            o[f"{k}：上漲比例%"] = r1((x > 0).mean() * 100)
            o[f"{k}：最糟%"] = r1(x.min() * 100)
    return o


def episodes(th, gap=21):
    above = v_on_spx >= th
    prev = above.rolling(gap, min_periods=gap).max().shift(1).fillna(1)
    return list(v_on_spx.index[above & (prev == 0)])


res = {"說明": __doc__, "資料": {"VIX": f"{vix.index[0].date()}～{vix.index[-1].date()}", "S&P 500": f"{spx.index[0].date()}～{spx.index[-1].date()}",
                                 "加權指數": f"{twii.index[0].date()}～{twii.index[-1].date()}"},
       "最新": {"VIX": [str(vix.index[-1].date()), float(vix.iloc[-1])], "S&P 500": [str(spx.index[-1].date()), float(spx.iloc[-1])],
              "加權指數": [str(twii.index[-1].date()), float(twii.iloc[-1])]}}
spx_days = spx.index[spx.index >= vix.index[0]]
res["S&P 500：所有日子（1990 起）"] = stats(FS, spx_days)
tw_all = twii.index
res["加權指數：所有日子（1997/7 起）"] = stats(FT, tw_all)
for th in (25, 30, 35, 40, 50):
    days = v_on_spx.index[(v_on_spx >= th) & (v_on_spx.index >= vix.index[0])]
    eps = episodes(th)
    res[f"VIX≥{th}"] = {"S&P 500 每一天": stats(FS, days), "S&P 500 每一波第一天": stats(FS, eps),
                        "加權指數 每一天": stats(FT, pd.DatetimeIndex([x for x in (tw_entry(d) for d in days) if x is not None]).unique()),
                        "加權指數 每一波第一天": stats(FT, pd.DatetimeIndex([x for x in (tw_entry(d) for d in eps) if x is not None]).unique()),
                        "每一波第一天（日期、VIX、S&P 6個月%、12個月%、半年內最多再跌%；加權 6個月%、12個月%）": [
                            [str(d.date()), round(float(v_on_spx[d]), 1), r1(FS["6個月"].get(d, np.nan) * 100), r1(FS["12個月"].get(d, np.nan) * 100),
                             r1(FS["半年內最多再跌"].get(d, np.nan) * 100),
                             r1(FT["6個月"].get(tw_entry(d), np.nan) * 100) if tw_entry(d) is not None else None,
                             r1(FT["12個月"].get(tw_entry(d), np.nan) * 100) if tw_entry(d) is not None else None] for d in eps]}
# 貼文那天（2026/3/27 美股收盤，台北 3/28 凌晨）
for d in ("2026-03-27",):
    d = pd.Timestamp(d)
    te = tw_entry(d)
    res[f"貼文那天 {d.date()}"] = {"VIX 收盤": float(v_on_spx[d]), "S&P 500": float(spx[d]),
                                  "S&P 1、3、6 個月後%": [r1(FS[k].get(d, np.nan) * 100) for k in ("1個月", "3個月", "6個月")],
                                  "加權（隔天 " + str(te.date()) + "）": float(twii[te]),
                                  "加權 1、3、6 個月後%": [r1(FT[k].get(te, np.nan) * 100) for k in ("1個月", "3個月", "6個月")]}
os.makedirs("out", exist_ok=True)
json.dump(res, open("out/vix_check.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "說明"}, ensure_ascii=False, indent=1))
