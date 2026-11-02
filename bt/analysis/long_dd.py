import sys
import numpy as np
import pandas as pd
sys.path.insert(0, ".")
src = open("long_report.py", encoding="utf-8").read()
exec(src[:src.index("# ---------- 帳戶模擬 ----------")].replace('a = pd.read_pickle("out/long_trades.pkl")', 'a = pd.read_pickle("out/long_trades.pkl")').split('say(f"名單交易')[0])
exec(src[src.index("# ---------- 帳戶模擬 ----------"):src.index("bt_s = pd.Series")])
bt_s = pd.Series(tx[start + 1:], index=dates[start + 1:]).dropna()
for nm, s in [("加權", bt_s), ("10 檔每天補", sim(10, False)), ("5 檔每天補", sim(5, False)), ("20 檔每天補", sim(20, False))]:
    dd = s / s.cummax() - 1
    tr = dd.idxmin(); pk_ = s.loc[:tr].idxmax()
    rec = s.loc[tr:]; back = rec[rec >= s.loc[pk_]]
    print(nm, f"最大回檔 {dd.min()*100:.1f}%", "高點", pk_.date(), "低點", tr.date(), "回到高點", back.index[0].date() if len(back) else "還沒")
    # 前三大回檔
    eps, i0 = [], None
    print("  年底淨值", s.resample("YE").last().round(2).to_dict() if nm != "加權" else "")
