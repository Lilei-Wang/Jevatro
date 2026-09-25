# -*- coding: utf-8 -*-
"""迭代11同种子回归：新代码重跑接力赛里 Jev 打过的种子，与基线对比。"""
import json
import os
import subprocess
import time
from pathlib import Path

import jev_bot
from client import BalatroClient

HERE = Path(__file__).parent
GAME_EXE = r"D:\software\Steam\steamapps\common\Balatro\Balatro.exe"
SEEDS = ["DEMOV42", "DEMOV44", "DEMOV48", "DEMOV50", "DEMOV58", "DEMOV74"]
BASELINE = {"DEMOV42": 5, "DEMOV44": 4, "DEMOV48": 4,
            "DEMOV50": 4, "DEMOV58": 5, "DEMOV74": 4}  # 接力赛 Jev 臂战绩


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
        results[seed] = gs.get("ante_num")
        print(f"[reg] {seed}: ante {gs.get('ante_num')} (基线 {BASELINE[seed]})", flush=True)
    except (Exception, SystemExit) as e:
        results[seed] = None
        print(f"[reg] {seed}: 异常 {type(e).__name__}", flush=True)

ok = [v for v in results.values() if v is not None]
print("\n==== 回归汇总 ====", flush=True)
print("新代码:", {k: v for k, v in results.items()}, flush=True)
print("基线:  ", BASELINE, flush=True)
if ok:
    print(f"新均值 {sum(ok)/len(ok):.2f} vs 基线均值 "
          f"{sum(BASELINE.values())/len(BASELINE):.2f}", flush=True)
(HERE / "logs" / "iter11_regression.txt").write_text(
    json.dumps({"new": results, "baseline": BASELINE}, ensure_ascii=False, indent=1),
    encoding="utf-8")
