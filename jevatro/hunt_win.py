"""jev 配置多种子冲关狩猎：寻找首胜并进入无限模式记录最深深度。"""
import time

import jev_bot

best = {"ante": 0, "seed": None}
for i in range(9, 17):
    seed = f"JEVATRO{i}"
    print(f"\n===== {seed} · jev =====", flush=True)
    try:
        gs = jev_bot.run(seed=seed)
        ante = gs.get("ante_num") or 0
        won = gs.get("won")
        print(f"[hunt] {seed}: won={won} ante={ante}")
        if ante > best["ante"]:
            best = {"ante": ante, "seed": seed, "won": won}
        if won:
            print(f"[hunt] 首胜! {seed} 进入无限模式, 最深 ante={ante}")
            break
    except Exception as e:
        print(f"[hunt] {seed} crash: {type(e).__name__}: {e}")
    time.sleep(2)
print("BEST:", best)
