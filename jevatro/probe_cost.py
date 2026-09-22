# -*- coding: utf-8 -*-
"""验证记账链路：真实调用 Jev 与 DeepSeek 各一次，检查 usage/cost 字段落盘。"""
import json

import pricing
from jev_layer import JevLayer
from llm_layer import LlmLayer
from logger import RunLogger

log = RunLogger(tag="costprobe")

# --- Jev 一次批量调用 -------------------------------------------------------
jl = JevLayer(log=log)
try:
    from typesafe_sdk import Choice, Noul
    resp = jl.ask("当前金钱20, 商店有小丑'Joker Jr'(基础+4分), 手牌区已有2个小丑。",
                  {"buy": Noul(instructions="是否值得花4元买下该小丑"),
                   "pick": Choice(instructions="本局主力牌型方向",
                                  criteria={"a": "对子", "b": "同花", "c": "高牌"})})
    print("Jev answers:", {k: str(v)[:60] for k, v in resp.answers.items()})
except Exception as e:
    print("Jev 调用失败:", e)
print(f"Jev 层: calls={jl.calls} in={jl.in_tokens} out={jl.out_tokens} "
      f"cost=${jl.cost_usd:.6f}")

# --- DeepSeek 一次 chat 调用 -------------------------------------------------
ll = LlmLayer(log=log)
try:
    reply = ll._chat('当前金钱20, 商店有小丑"Joker Jr"(基础+4分)。'
                     '只输出JSON: {"buy": true/false, "reason": "一句话"}')
    print("LLM reply:", reply[:120].replace("\n", " "))
except Exception as e:
    print("LLM 调用失败:", e)
print(f"LLM 层: calls={ll.calls} in={ll.in_tokens} (hit={ll.in_hit_tokens}/miss={ll.in_miss_tokens}) "
      f"out={ll.out_tokens} cost=${ll.cost_usd:.6f}")

log.close()

# --- 检查落盘记录 -----------------------------------------------------------
for line in open(log.path, encoding="utf-8"):
    r = json.loads(line)
    if r["kind"] in ("jev", "llm"):
        slim = {k: r[k] for k in ("kind", "model", "in_tokens", "out_tokens",
                                  "in_hit_tokens", "in_miss_tokens", "cost_usd", "latency")
                if k in r}
        print("落盘:", slim)
print("日志文件:", log.path)
