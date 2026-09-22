"""冲关狩猎：给定种子区间用 jev 配置找首胜，胜利后自动进入无限模式记录最深深度。

用法: python hunt_win.py [起始编号] [结束编号]   # 默认 17 32
"""
import sys
import time

import jev_bot

start = int(sys.argv[1]) if len(sys.argv) > 1 else 17
end = int(sys.argv[2]) if len(sys.argv) > 2 else 32

best = {"ante": 0, "seed": None, "won": False}
for i in range(start, end + 1):
    seed = f"JEVATRO{i}"
    print(f"\n===== {seed} · jev =====", flush=True)
    try:
        gs = jev_bot.run(seed=seed)
        ante = gs.get("ante_num") or 0
        won = gs.get("won")
        print(f"[hunt] {seed}: won={won} 最深ante={ante}")
        if ante > best["ante"]:
            best = {"ante": ante, "seed": seed, "won": bool(won)}
        if won:
            print(f"[hunt] 首胜! {seed} 无限模式打到 ante={ante}")
            break
    except Exception as e:
        print(f"[hunt] {seed} crash: {type(e).__name__}: {e}")
    time.sleep(2)
print("BEST:", best)
