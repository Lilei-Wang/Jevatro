# -*- coding: utf-8 -*-
"""迭代12：20 个新种子大样本批跑（迭代11代码），狩猎首胜 + 死因数据采集。"""
import json
import os
import subprocess
import time
from pathlib import Path

import jev_bot
from client import BalatroClient

HERE = Path(__file__).parent
GAME_EXE = r"D:\software\Steam\steamapps\common\Balatro\Balatro.exe"
SEEDS = [f"DEMW{i}" for i in range(1, 21)]


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
    print("[heal] 游戏进程不在，重启…", flush=True)
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
        results[seed] = {"ante": gs.get("ante_num"), "won": gs.get("won"),
                         "money": gs.get("money"),
                         "n_jokers": (gs.get("jokers") or {}).get("count")}
        print(f"[i12] {seed}: won={gs.get('won')} ante={gs.get('ante_num')} "
              f"money=${gs.get('money')} jokers={(gs.get('jokers') or {}).get('count')}",
              flush=True)
        if gs.get("won"):
            print(f"[i12] 🏆🏆 首胜！！！种子 {seed}", flush=True)
    except (Exception, SystemExit) as e:
        results[seed] = {"error": f"{type(e).__name__}"}
        print(f"[i12] {seed}: 异常 {type(e).__name__}", flush=True)

ok = [v["ante"] for v in results.values() if v.get("ante") is not None]
print("\n==== 迭代12 批跑汇总 ====", flush=True)
if ok:
    print(f"均值 Ante {sum(ok)/len(ok):.2f} · 最深 {max(ok)} · 局数 {len(ok)}", flush=True)
(HERE / "logs" / "iter12_batch.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved logs/iter12_batch.json", flush=True)
