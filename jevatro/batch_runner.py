"""多种子 A/B 批量对比：naive（solver-only）vs jev（solver+Jev）。

用法: python batch_runner.py [种子数]     # 默认 5 个种子（JEVATRO1..N）
前提: 带 balatrobot 的游戏运行中。输出 logs/batch_summary.md + JSON。
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import jev_bot
import naive_bot

LOGS = Path(__file__).parent / "logs"


def batch(n_seeds: int = 5) -> list[dict]:
    rows = []
    seeds = [f"JEVATRO{i}" for i in range(1, n_seeds + 1)]
    for seed in seeds:
        for tag, mod, run in (("naive", "A/B 基线", naive_bot),
                              ("jev", "solver+Jev", jev_bot)):
            print(f"\n===== {seed} · {tag} =====", flush=True)
            t0 = time.time()
            try:
                gs = run.run(seed=seed)
                rows.append({
                    "seed": seed, "config": tag,
                    "won": gs.get("won"), "ante": gs.get("ante_num"),
                    "round": gs.get("round_num"),
                    "money": gs.get("money"), "n_jokers": (gs.get("jokers") or {}).get("count"),
                    "wall_s": round(time.time() - t0, 1),
                })
            except Exception as e:  # 单局崩溃不炸整批，记录后继续
                rows.append({"seed": seed, "config": tag, "error": f"{type(e).__name__}: {e}"})
                import traceback
                traceback.print_exc()
            time.sleep(2)
    _write_summary(rows)
    return rows


def _write_summary(rows: list[dict]):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (LOGS / f"batch_{stamp}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# 多种子 A/B 对比", "",
             "| 种子 | 配置 | 结果 | Ante | 轮 | 金币 | 小丑 | 用时(s) |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['seed']} | {r['config']} | "
            f"{'🏆胜' if r.get('won') else '💀败'} | {r.get('ante','-')} | "
            f"{r.get('round','-')} | {r.get('money','-')} | {r.get('n_jokers','-')} | "
            f"{r.get('wall_s','-')} |")
    for cfg in ("naive", "jev"):
        sub = [r for r in rows if r["config"] == cfg and "ante" in r]
        if sub:
            avg = sum(r["ante"] for r in sub) / len(sub)
            lines.append(f"\n**{cfg}**: 平均到达 Ante {avg:.2f}（{len(sub)} 局）")
    text = "\n".join(lines)
    (LOGS / "batch_summary.md").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    batch(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
