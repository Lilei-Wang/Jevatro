"""深度 A/B 对比：有 Jev vs 无 Jev（同种子成对比较）。

解析 logs/ 下所有 run_{naive,jev}_*.jsonl，按 (seed, config) 取最新一局，
计算战绩与行为差异指标，输出 logs/ab_report.md。
"""
from __future__ import annotations

import io
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LOGS = Path(__file__).parent / "logs"


def parse_run(path: Path) -> dict | None:
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    start = next((r for r in recs if r["kind"] == "game_start"), None)
    result = next((r for r in recs if r["kind"] == "result"), None)
    if not start or not result:
        return None
    acts = [r for r in recs if r["kind"] == "action"]
    plays = [r for r in acts if r["method"] == "play" and not r.get("error")]
    hand_scores = [r["after"].get("chips", 0) - r["before"].get("chips", 0) for r in plays]
    buys_by_set = defaultdict(int)
    for r in acts:
        if r["method"] == "buy" and not r.get("error"):
            why = str((r.get("extra") or {}).get("why", ""))
            key = why.split()[0] if why else "?"
            if key.startswith("j_"):
                buys_by_set["JOKER"] += 1
            elif key.startswith(("c_mercury", "c_venus", "c_earth", "c_mars", "c_jupiter",
                                  "c_saturn", "c_uranus", "c_neptune", "c_pluto",
                                  "c_planet_x", "c_ceres", "c_eris")):
                buys_by_set["PLANET"] += 1
            elif key.startswith("c_"):
                buys_by_set["CONSUMABLE"] += 1
            elif key.startswith("v_"):
                buys_by_set["VOUCHER"] += 1
            else:
                buys_by_set["OTHER"] += 1
    jev_recs = [r for r in recs if r["kind"] == "jev"]
    llm_recs = [r for r in recs if r["kind"] == "llm"]
    return {
        "seed": start.get("seed"),
        "file": path.name,
        "mtime": path.stat().st_mtime,
        "won": result["final"].get("won"),
        "ante": result["final"].get("ante"),
        "round": result["final"].get("round"),
        "actions": result.get("actions", len(acts)),
        "illegal": result.get("illegal", 0),
        "duration": result.get("duration"),
        "plays": len(plays),
        "max_hand": max(hand_scores) if hand_scores else 0,
        "total_scored": sum(hand_scores),
        "discards": sum(1 for r in acts if r["method"] == "discard" and not r.get("error")),
        "skips": sum(1 for r in acts if r["method"] == "skip" and not r.get("error")),
        "sells": sum(1 for r in acts if r["method"] == "sell" and not r.get("error")),
        "uses": sum(1 for r in acts if r["method"] == "use" and not r.get("error")),
        "buys": sum(1 for r in acts if r["method"] == "buy" and not r.get("error")),
        **{f"buy_{k}": v for k, v in buys_by_set.items()},
        "jev_calls": len(jev_recs),
        "jev_latency": round(sum(r.get("latency", 0) for r in jev_recs), 1),
        "llm_calls": len(llm_recs),
        "llm_latency": round(sum(r.get("latency", 0) for r in llm_recs), 1),
        "llm_in_tokens": sum(r.get("in_tokens", 0) for r in llm_recs),
        "llm_out_tokens": sum(r.get("out_tokens", 0) for r in llm_recs),
    }


def collect() -> dict[tuple[str, str], dict]:
    groups: dict[tuple[str, str], dict] = {}
    for path in sorted(LOGS.glob("run_*.jsonl")):
        if "_jev_" in path.name:
            cfg = "jev"
        elif "_llm_" in path.name:
            cfg = "llm"
        else:
            cfg = "naive"
        m = parse_run(path)
        if not m or not m["seed"]:
            continue
        key = (m["seed"], cfg)
        if key not in groups or m["mtime"] > groups[key]["mtime"]:
            groups[key] = m
    return groups


def report() -> str:
    groups = collect()
    cfgs = [c for c in ("naive", "jev", "llm") if any(k[1] == c for k in groups)]
    need = ("naive", "jev", "llm")[: len(cfgs)]
    seeds = sorted({s for s, c in groups if (s, "jev") in groups and (s, "naive") in groups})
    if "llm" in cfgs:
        seeds = [s for s in seeds if (s, "llm") in groups]
    lines = [f"# 三配置深度对比（{len(seeds)} 个种子 × {len(cfgs)} 配置，共 {len(seeds) * len(cfgs)} 局）",
             "", "生成时间: " + datetime.now().strftime("%Y-%m-%d %H:%M"), ""]
    if not seeds:
        return "\n".join(lines + ["（无成对数据：请先用 batch_runner.py 跑批量）"])

    header = ("| 种子 | " + " | ".join(f"{c}: Ante/轮" for c in cfgs) + " | 最深单手分 " +
              " / ".join(cfgs) + " |")
    lines += [header, "|" + "---|" * (1 + len(cfgs) + 1)]
    wins = {c: 0 for c in cfgs}
    for s in seeds:
        row = [groups[(s, c)] for c in cfgs]
        best = max(r["ante"] for r in row)
        for r in row:
            if r["ante"] == best:
                wins[groups and next(c for c in cfgs if groups[(s, c)] is r)] += 1
        lines.append(
            f"| {s} | " + " | ".join(f"{r['ante']}/{r['round']}" for r in row) + " | " +
            " / ".join(str(r["max_hand"]) for r in row) + " |")

    lines += ["", "## 汇总（均值）", "",
              "| 指标 | " + " | ".join(cfgs) + " |", "|---" * (len(cfgs) + 1) + "|"]
    for k, label in (("ante", "到达 Ante"), ("round", "到达轮"),
                     ("max_hand", "最大单手分"), ("total_scored", "全场总得分"),
                     ("buys", "购买数"), ("uses", "消耗牌使用数"),
                     ("skips", "跳盲数"), ("discards", "弃牌数"),
                     ("illegal", "非法动作"), ("duration", "对局时长(s)")):
        vals = []
        for c in cfgs:
            sub = [groups[(s, c)][k] for s in seeds if groups[(s, c)].get(k) is not None]
            vals.append(f"{sum(sub) / len(sub):.2f}" if sub else "-")
        lines.append(f"| {label} | " + " | ".join(vals) + " |")

    for c, kind, lat_key, call_key in (("jev", "Jev", "jev_latency", "jev_calls"),
                                       ("llm", "LLM", "llm_latency", "llm_calls")):
        if c not in cfgs:
            continue
        ms = [groups[(s, c)] for s in seeds]
        calls = sum(m[call_key] for m in ms)
        lat = sum(m[lat_key] for m in ms)
        extra = ""
        if c == "llm":
            tin = sum(m.get("llm_in_tokens", 0) for m in ms)
            tout = sum(m.get("llm_out_tokens", 0) for m in ms)
            extra = f"，{tin} in / {tout} out tokens（glm-4-flash 免费档）"
        lines += ["", f"## {kind} 层开销", "",
                  f"- 总调用 {calls} 次，决策总延迟 {lat:.1f}s（平均 {lat / max(calls, 1):.2f}s/次）{extra}"]
        if c == "jev":
            lines.append(f"- 输入按 ~2K tokens/次估算：{calls * 2000 / 1e6:.2f}M tokens ≈ "
                         f"${calls * 2000 / 1e6 * 0.042:.4f}（输出免费）")

    lines += ["", "## 胜负计数（并列计胜）", ""] + [
        f"- {c}: {wins[c]} 局最深" for c in cfgs]
    text = "\n".join(lines)
    (LOGS / "ab_report.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(report())
