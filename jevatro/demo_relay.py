# -*- coding: utf-8 -*-
"""录制接力守护：连续开新局供录制，游戏进程崩溃时自动重启恢复。

用法: python demo_relay.py [起始编号] [总局数]    # 默认 19 起，最多 60 局
依赖: dashboard.py 独立运行中（面板自动"跟随最新"）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import jev_bot
from client import BalatroClient

HERE = Path(__file__).parent
GAME_EXE = r"D:\software\Steam\steamapps\common\Balatro\Balatro.exe"


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


def main(start: int = 19, total: int = 60):
    for i in range(start, start + total):
        if not ensure_game():
            print("[relay] 游戏重启失败，终止接力", flush=True)
            return
        print(f"\n===== DEMOV{i} =====", flush=True)
        try:
            gs = jev_bot.run(seed=f"DEMOV{i}")
            print(f"[relay] DEMOV{i}: won={gs.get('won')} ante={gs.get('ante_num')}",
                  flush=True)
        except (Exception, SystemExit) as e:
            print(f"[relay] DEMOV{i} 异常: {type(e).__name__}: {e}", flush=True)
        time.sleep(2)
    print("[relay] 接力完成", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 19,
         int(sys.argv[2]) if len(sys.argv) > 2 else 60)
