第 7 版權重（2026-11-05：法人買超天數 50、營收 35、千張大戶 15，其他 0 分）重算網站上所有 12 年回測數字。
腳本跟上一層 bt/analysis 的同名檔一樣，只有 long_setup.py 的分數那一行換成第 7 版；在跟 bt/ 同一層的資料夾執行（資料路徑是 ../bt-branch/bt/raw）。
一次只能跑一個（每個要 3～4 GB 記憶體）：site_numbers3 → long_check → site_numbers → rank_split → long_rules → long_report → solutions。
