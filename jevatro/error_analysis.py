"""Jev 决策分桶分析：聚合所有 jev 局的问答数据，定位最弱的决策环节。

输出 logs/error_analysis.md。
"""
from __future__ import annotations

import io
import json
from collections import Counter, defaultdict
from pathlib import Path

LOGS = Path(__file__).parent / "logs"
DIMS = ("synergy", "scaling", "economy", "immediate")


def analyze() -> str:
    files = sorted(LOGS.glob("run_jev_*.jsonl"))
    dim_scores = defaultdict(list)          # dim -> [score]
    dim_conf = defaultdict(list)            # dim -> [conf]
    arch_picks = Counter()                  # 方向 argmax 分布
    skip_nouls = []                         # 跳盲 noul 值
    reroll_nouls = []
    jev_lat = []
    per_file = []

    for path in files:
        recs = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        has_result = any(r["kind"] == "result" for r in recs)
        if not has_result:
            continue
        result = next(r for r in recs if r["kind"] == "result")
        buys = [r for r in recs if r["kind"] == "action" and r["method"] == "buy" and not r.get("error")]
        n_jev = sum(1 for r in recs if r["kind"] == "jev")
        per_file.append({"file": path.name, "ante": result["final"].get("ante"),
                         "buys": len(buys), "jev": n_jev})
        for r in recs:
            if r["kind"] != "jev":
                continue
            jev_lat.append(r.get("latency", 0))
            for k, a in r.get("answers", {}).items():
                if "__" in k:
                    dim = k.split("__")[1]
                    if dim in DIMS and a.get("type") == "score":
                        dim_scores[dim].append(a.get("score", 0))
                        if a.get("confidence") is not None:
                            dim_conf[dim].append(a["confidence"])
                elif k == "skip_better":
                    skip_nouls.append(a.get("noul", 0))
                elif k == "reroll_worth":
                    reroll_nouls.append(a.get("noul", 0))
            # 方向识别（兼容旧版 arch_* Noul 与新版 archetype Choice）
            arch_old = {k[5:]: a.get("noul", 0) for k, a in r.get("answers", {}).items()
                        if k.startswith("arch_")}
            if arch_old:
                best = max(arch_old, key=arch_old.get)
                if arch_old[best] >= 0.50:
                    arch_picks[best] += 1
                else:
                    arch_picks["(未达阈值→default)"] += 1
            elif "archetype" in r.get("answers", {}):
                ch = r["answers"]["archetype"].get("choice", "?")
                arch_picks[ch] += 1

    def _avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    lines = ["# Jev 决策分桶分析", ""]
    lines.append(f"样本：{len(per_file)} 局（含完整结果）、{len(jev_lat)} 次调用")
    lines.append("")
    lines.append("## 四维打分均值（0-4）与平均置信度")
    lines.append("")
    lines.append("| 维度 | 平均分 | 平均置信度 | 样本数 |")
    lines.append("|---|---|---|---|")
    for d in DIMS:
        lines.append(f"| {d} | {_avg(dim_scores[d]):.2f} | {_avg(dim_conf[d]):.3f} | {len(dim_scores[d])} |")
    lines.append("")
    lines.append("## 方向识别（argmax 分布）")
    lines.append("")
    for k, v in arch_picks.most_common():
        lines.append(f"- {k}: {v} 次")
    lines.append("")
    if skip_nouls:
        lines.append(f"## 跳盲决策：{len(skip_nouls)} 次，均值 noul={_avg(skip_nouls):.2f}"
                     f"（>0.65 才跳）实际跳过次数见 ab_report")
    if reroll_nouls:
        lines.append(f"\n## 重掷判断：{len(reroll_nouls)} 次，均值 noul={_avg(reroll_nouls):.2f}")
    lines.append(f"\n## 调用延迟：平均 {_avg(jev_lat):.2f}s / 次")
    lines.append("")
    lines.append("## 弱点定位建议")
    lines.append("")
    weakest = min(DIMS, key=lambda d: _avg(dim_conf[d]))
    lines.append(f"- 置信度最低的维度是 **{weakest}**（{_avg(dim_conf[weakest]):.3f}）——优先重写该维度 rubric 措辞")
    if arch_picks.get("(未达阈值→default)", 0) > sum(v for k, v in arch_picks.items() if k != "(未达阈值→default)") * 0.5:
        lines.append("- 超过一半的商店方向识别未达阈值 → 方向题区分度不足，考虑改成 Choice 单选题")
    lines.append("- 后续：按'购买后 2 轮内死亡'标注坏购买，做购买级错误归因（需对局级标注）")

    text = "\n".join(lines)
    (LOGS / "error_analysis.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(analyze())
