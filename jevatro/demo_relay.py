# -*- coding: utf-8 -*-
"""录制接力守护：连续开新局供录制，游戏进程崩溃时自动重启恢复。

用法: python demo_relay.py [起始编号] [总局数] [模式]
模式: jev（默认，只用 Jev 大脑）| llm（只用 DeepSeek 大脑）| mix（两种大脑轮流，界面对比）
依赖: dashboard.py 独立运行中（面板自动"跟随最新"，两种大脑的决策流都能展示）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import jev_bot
import llm_bot
from client import BalatroClient

HERE = Path(__file__).parent
GAME_EXE = r"D:\software\Steam\steamapps\common\Balatro\Balatro.exe"
BOTS = {"jev": jev_bot, "llm": llm_bot}


def game_alive() -> bool:
    try:
        import requests
        r = requests.post("http://127.0.0.1:12346",
                          json={"jsonrpc": "2.0", "method": "health", "id": 1},
                          timeout=3)
        return r.json().get("result", {}).get("status") == "ok"
    except Exception:
        return False


def ensure_game() -> bool:
    if game_alive():
        return True
    print("[relay] 游戏进程不在，重启…", flush=True)
    subprocess.run(["taskkill", "/im", "Balatro.exe", "/f"], capture_output=True)
    time.sleep(3)
    os.startfile(GAME_EXE)  # noqa: P101
    ok = BalatroClient().wait_online(tries=45, delay=2.0)
    if ok:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(HERE / "position_windows.ps1")], capture_output=True)
    print(f"[relay] 游戏恢复: {ok}", flush=True)
    return ok


def main(start: int = 19, total: int = 60, mode: str = "jev"):
    for i in range(start, start + total):
        if not ensure_game():
            print("[relay] 游戏重启失败，终止接力", flush=True)
            return
        cfg = mode if mode != "mix" else ("jev" if i % 2 == 0 else "llm")
        print(f"\n===== DEMOV{i} · {cfg.upper()} =====", flush=True)
        try:
            gs = BOTS[cfg].run(seed=f"DEMOV{i}")
            print(f"[relay] DEMOV{i}({cfg}): won={gs.get('won')} ante={gs.get('ante_num')}",
                  flush=True)
        except (Exception, SystemExit) as e:
            print(f"[relay] DEMOV{i}({cfg}) 异常: {type(e).__name__}: {e}", flush=True)
        time.sleep(2)
    print("[relay] 接力完成", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 19,
         int(sys.argv[2]) if len(sys.argv) > 2 else 60,
         sys.argv[3] if len(sys.argv) > 3 else "jev")
