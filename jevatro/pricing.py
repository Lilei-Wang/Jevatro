"""模型价格表与成本计算（官方价格，来源与查价日期随报告落盘）。

价格查证记录：
- Jev (TypeSafe AI System One): 输入 $0.042/百万 tokens（早鸟价 $42/十亿），
  输出免费（官方称"too cheap to meter"）。
  来源: https://typesafe.ai （2026-09-22 查证）
- DeepSeek deepseek-flash (DeepSeek-V4.1-Flash), USD/百万 tokens:
  输入缓存未命中 $0.30 / 命中 $0.006，输出 $1.20（高峰价）；
  非高峰（工作日高峰时段之外）一律半价。
  来源: https://api-docs.deepseek.com/quick_start/pricing （2026-09-22 查证）
"""
from __future__ import annotations

import math

USD_TO_CNY = 7.1  # 近似汇率，仅用于人民币参考展示（非计费汇率）

PRICES: dict[str, dict] = {
    "jev": {
        "provider": "TypeSafe AI Jev (System One)",
        "input_per_m": 0.042,   # USD / 百万输入 tokens
        "output_per_m": 0.0,    # 输出免费
        "source": "https://typesafe.ai",
        "checked": "2026-09-22",
    },
    "deepseek-flash": {
        "provider": "DeepSeek V4.1-Flash",
        "in_miss_per_m": 0.30,  # USD / 百万输入 tokens（缓存未命中，高峰）
        "in_hit_per_m": 0.006,  # USD / 百万输入 tokens（缓存命中，高峰）
        "out_per_m": 1.20,      # USD / 百万输出 tokens（高峰）
        "offpeak_ratio": 0.5,   # 非高峰一律半价
        "source": "https://api-docs.deepseek.com/quick_start/pricing",
        "checked": "2026-09-22",
    },
}


def jev_cost_usd(in_tokens: int, out_tokens: int) -> float:
    p = PRICES["jev"]
    return in_tokens / 1e6 * p["input_per_m"] + out_tokens / 1e6 * p["output_per_m"]


def llm_cost_usd(in_miss: int, in_hit: int, out_tokens: int,
                 model: str = "deepseek-flash", offpeak: bool = False) -> float:
    """按 DeepSeek 峰谷定价计算；默认高峰价（保守上界）。"""
    key = model if model in PRICES else "deepseek-flash"
    p = PRICES[key]
    r = p.get("offpeak_ratio", 1.0) if offpeak else 1.0
    return (in_miss / 1e6 * p["in_miss_per_m"]
            + in_hit / 1e6 * p["in_hit_per_m"]
            + out_tokens / 1e6 * p["out_per_m"]) * r


def est_tokens(text: str) -> int:
    """旧日志无实测 usage 时的估算：除数 0.93 字符/token。

    系数由 COST9 局 27 次实测校准（中文状态文本 ≈ 1.08 token/字符）。"""
    return math.ceil(len(text) / 0.93) if text else 0


def price_table_md() -> list[str]:
    """价格表（markdown 行），供各报告引用。"""
    j, d = PRICES["jev"], PRICES["deepseek-flash"]
    return [
        "| 模型 | 计费项 | 高峰价 (USD/百万tokens) |",
        "|---|---|---|",
        f"| Jev (System One) | 输入 | ${j['input_per_m']:.3f} |",
        f"| Jev (System One) | 输出 | 免费 |",
        f"| deepseek-flash | 输入·缓存未命中 | ${d['in_miss_per_m']:.3f} |",
        f"| deepseek-flash | 输入·缓存命中 | ${d['in_hit_per_m']:.3f} |",
        f"| deepseek-flash | 输出 | ${d['out_per_m']:.3f} |",
        "",
        f"- 价格查证日期：Jev {j['checked']}（{j['source']}）；"
        f"deepseek-flash {d['checked']}（{d['source']}）",
        f"- DeepSeek 非高峰时段一律 {int((1 - d['offpeak_ratio']) * 100)}% 折扣，"
        "本报告按高峰价计算（保守上界）",
        f"- 人民币参考按 1 USD ≈ {USD_TO_CNY} CNY 折算（近似，非计费汇率）",
    ]
