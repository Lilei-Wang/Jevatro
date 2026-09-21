"""补跑指定种子的两配置对局：python rerun_seeds.py JEVATRO7 JEVATRO8"""
import sys
import time

import jev_bot
import naive_bot

for seed in sys.argv[1:]:
    for tag, run in (("naive", naive_bot), ("jev", jev_bot)):
        print(f"\n===== {seed} · {tag} =====", flush=True)
        try:
            run.run(seed=seed)
        except Exception as e:
            print(f"[crash] {tag}: {type(e).__name__}: {e}")
        time.sleep(2)
print("RERUN DONE")
