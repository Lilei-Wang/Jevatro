# -*- coding: utf-8 -*-
"""迭代13回归：攥钱死种子重跑，基线=迭代12成绩。"""
import json
import os
import subprocess
import time
from pathlib import Path

import jev_bot
from client import BalatroClient

HERE = Path(__file__).parent
GAME_EXE = r"D:\software\Steam\steamapps\common\Balatro\Balatro.exe"
SEEDS = ["DEMW20", "DEMW4", "DEMW19", "DEMW6", "DEMW1", "DEMW5"]
BASELINE = {"DEMW20": 4, "DEMW4": 5, "DEMW19": 4, "DEMW6": 4, "DEMW1": 3, "DEMW5": 3}


def game_alive() -> bool:
    try:
        import requests
        r = requests.post("http://127.0.0.1:12346",
                          json={"jsonrpc": "2.0", "method": "health", "id": 1}, timeout=3)
        return r.json().get("result", {}).get("status") == "ok"
    except Exception:
        return False


def ensure_game():
    if game_alive():
        return
    subprocess.run(["taskkill", "/im", "Balatro.exe", "/f"], capture_output=True)
    time.sleep(3)
    os.startfile(GAME_EXE)  # noqa: P101
    BalatroClient().wait_online(tries=45, delay=2.0)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(HERE / "position_windows.ps1")], capture_output=True)


results = {}
for seed in SEEDS:
    ensure_game()
    try:
        gs = jev_bot.run(seed=seed)
        results[seed] = {"ante": gs.get("ante_num"), "money": gs.get("money")}
        print(f"[i13] {seed}: ante {gs.get('ante_num')} 死时${gs.get('money')} "
              f"(基线 ante{BASELINE[seed]})", flush=True)
    except (Exception, SystemExit) as e:
        results[seed] = {"error": type(e).__name__}
        print(f"[i13] {seed}: 异常 {type(e).__name__}", flush=True)

ok = [v["ante"] for v in results.values() if v.get("ante") is not None]
money = [v.get("money") for v in results.values() if v.get("money") is not None]
print("\n==== 迭代13回归 ====", flush=True)
print(f"新均值 {sum(ok)/len(ok):.2f} vs 基线 {sum(BASELINE.values())/len(BASELINE):.2f}"
      f" · 死时金币均值 ${sum(money)/max(len(money),1):.0f}", flush=True)
(HERE / "logs" / "iter13_regression.txt").write_text(
    json.dumps({"new": results, "baseline": BASELINE}, ensure_ascii=False, indent=1),
    encoding="utf-8")
