"""死因分析：每一局是怎么死的？聚合全部 run 日志的终局特征。

输出：logs/death_analysis.md
维度：死亡盲注需求 vs 四手总分差距 / 小丑数量与类型 / 死时金币 / 购买次数。
"""
from __future__ import annotations

import io
import json
from collections import Counter
from pathlib import Path

LOGS = Path(__file__).parent / "logs"


def analyze_run(path: Path) -> dict | None:
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    result = next((r for r in recs if r.get("kind") == "result"), None)
    start = next((r for r in recs if r.get("kind") == "game_start"), None)
    if not result or not start:
        return None
    acts = [r for r in recs if r["kind"] == "action"]
    plays = [r for r in acts if r["method"] == "play" and not r.get("error")]

    # 最后一轮（死亡轮）的四手得分与盲注需求
    last_round = result["final"].get("round", 0)
    round_plays = [r for r in plays if r["before"].get("round") == last_round]
    scored = [r["after"].get("chips", 0) - r["before"].get("chips", 0)
              for r in round_plays]
    total = sum(scored)

    # 死亡时盲注需求（从最后一次 play 的 need 不可靠，改用最后一轮 before.ante 的 blind 表）
    need = None
    for r in reversed(recs):
        if r["kind"] == "jev" and "盲注需求" in str(r.get("state", "")):
            import re as _re
            m = _re.search(r"需(\d+)", r["state"])
            if m:
                need = int(m.group(1))
                break
    if need is None and round_plays:
        need = round_plays[0]["before"].get("chips", 0) + 10**9  # 未知

    buys = [r for r in acts if r["method"] == "buy" and not r.get("error")]
    joker_buys = sum(1 for b in buys
                     if str((b.get("extra") or {}).get("why", "")).startswith("j_"))
    # 小丑特征（终局 jokers 数在 result.final.n_jokers）
    n_jokers = result["final"].get("n_jokers") or 0

    cfg = ("jev" if "_jev_" in path.name
           else "llm" if "_llm_" in path.name else "naive")
    return {
        "file": path.name, "cfg": cfg,
        "ante": result["final"].get("ante"), "round": last_round,
        "need": need, "total": total,
        "gap": (need - total) if need is not None else None,
        "hands": len(scored), "max_hand": max(scored) if scored else 0,
        "money": result["final"].get("money"),
        "buys": len(buys), "joker_buys": joker_buys, "n_jokers": n_jokers,
        "won": result["final"].get("won"),
    }


def main() -> str:
    rows = []
    for p in sorted(LOGS.glob("run_*.jsonl")):
        try:
            r = analyze_run(p)
        except Exception:
            r = None
        if r and r["ante"] is not None:
            rows.append(r)

    lines = ["# 死因分析（全部对局终局特征）", ""]
    # 1) 死亡差距分布
    deep = [r for r in rows if (r["gap"] or 0) > 0]
    close = [r for r in deep if r["gap"] <= (r["need"] or 1) * 0.25]   # 差25%以内=惜败
    lines.append(f"- 样本 {len(rows)} 局（含完整终局）；其中可计算死因差距 {len(deep)} 局")
    if deep:
        lines.append(f"- **惜败局（差距≤需求25%）：{len(close)} 局"
                     f"（{len(close) / len(deep) * 100:.0f}%）——差一口气，多一手/一次好购买就能过")
        avg_gap = sum(r["gap"] for r in deep) / len(deep)
        lines.append(f"- 平均差距：{avg_gap:.0f} 分（相对需求 "
                     f"{sum(r['gap'] / r['need'] for r in deep) / len(deep) * 100:.0f}%）")
    # 2) 按配置聚合
    lines += ["", "## 按配置聚合", "",
              "| 配置 | 局数 | 平均Ante | 平均小丑数 | 平均购买 | 死时金币 | 惜败率 |",
              "|---|---|---|---|---|---|---|"]
    for cfg in ("naive", "jev", "llm"):
        sub = [r for r in rows if r["cfg"] == cfg]
        if not sub:
            continue
        cl = [r for r in sub if (r["gap"] or 0) > 0 and r["gap"] <= (r["need"] or 1) * 0.25]
        dn = len([r for r in sub if (r["gap"] or 0) > 0]) or 1
        lines.append(
            f"| {cfg} | {len(sub)} | {sum(r['ante'] for r in sub) / len(sub):.2f} "
            f"| {sum(r['n_jokers'] for r in sub) / len(sub):.1f} "
            f"| {sum(r['buys'] for r in sub) / len(sub):.1f} "
            f"| ${sum(r['money'] or 0 for r in sub) / len(sub):.0f} "
            f"| {len(cl) / dn * 100:.0f}% |")
    # 3) 深局（ante>=4）死因画像
    deep_runs = [r for r in rows if r["ante"] and r["ante"] >= 4]
    lines += ["", f"## 深局画像（ante≥4，共 {len(deep_runs)} 局）", ""]
    if deep_runs:
        lines.append(f"- 死时平均金币 ${sum(r['money'] or 0 for r in deep_runs) / len(deep_runs):.0f}"
                     f"（低金币=经济枯竭没得买）")
        lines.append(f"- 平均小丑 {sum(r['n_jokers'] for r in deep_runs) / len(deep_runs):.1f} 张")
        near = [r for r in deep_runs if (r["gap"] or 9e9) <= (r["need"] or 1) * 0.3]
        lines.append(f"- 深局惜败（差≤30%）：{len(near)} 局 —— "
                     "瓶颈是单轮爆发不足（X倍率/牌型等级），不是无牌可买" if near else
                     "- 深局多为大差距死亡 —— 战力曲线断裂")
    # 4) 代表性惜败局明细
    lines += ["", "## 惜败局明细（差距≤25%）", ""]
    for r in sorted(close, key=lambda x: x["gap"])[:12]:
        lines.append(f"- {r['file'][:26]}… {r['cfg']} ante{r['ante']}r{r['round']}: "
                     f"打出{r['total']}/{r['need']}（差{r['gap']}，{r['hands']}手，"
                     f"单手最高{r['max_hand']}，{r['n_jokers']}小丑，${r['money']}）")

    text = "\n".join(lines)
    (LOGS / "death_analysis.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(main())
