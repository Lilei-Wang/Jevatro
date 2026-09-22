"""仅跑 llm 臂于 N 种子（jev/naive 沿用同版本最新数据配对）。"""
import sys
import time

import llm_bot

for seed in [f"JEVATRO{i}" for i in range(1, int(sys.argv[1] if len(sys.argv) > 1 else 8) + 1)]:
    print(f"\n===== {seed} · llm(deepseek-flash) =====", flush=True)
    try:
        llm_bot.run(seed=seed)
    except Exception as e:
        print(f"[crash] {type(e).__name__}: {e}")
    time.sleep(2)
print("LLM_ARM_DONE")
