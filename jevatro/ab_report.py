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

import pricing

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
    jev_in = sum(r.get("in_tokens", 0) for r in jev_recs)
    jev_est = 0
    for r in jev_recs:
        if not r.get("in_tokens"):
            jev_est += pricing.est_tokens(
                r.get("state", "") + json.dumps(r.get("questions", {}), ensure_ascii=False))
    jev_cost = (sum(r.get("cost_usd", 0) for r in jev_recs)
                + pricing.jev_cost_usd(jev_est, 0))
    llm_cost = 0.0
    llm_hit = llm_miss = 0
    for r in llm_recs:
        if r.get("cost_usd") is not None:
            llm_cost += r.get("cost_usd", 0)
            llm_hit += r.get("in_hit_tokens", 0)
            llm_miss += r.get("in_miss_tokens", 0)
        else:
            in_t, out_t = r.get("in_tokens", 0), r.get("out_tokens", 0)
            if "glm" not in (r.get("model") or ""):
                llm_cost += pricing.llm_cost_usd(in_t, 0, out_t)
            llm_miss += in_t
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
        "jev_in_tokens": jev_in,
        "jev_in_est": jev_est,
        "jev_out_tokens": sum(r.get("out_tokens", 0) for r in jev_recs),
        "jev_cost_usd": round(jev_cost, 6),
        "llm_calls": len(llm_recs),
        "llm_latency": round(sum(r.get("latency", 0) for r in llm_recs), 1),
        "llm_in_tokens": sum(r.get("in_tokens", 0) for r in llm_recs),
        "llm_out_tokens": sum(r.get("out_tokens", 0) for r in llm_recs),
        "llm_in_hit": llm_hit,
        "llm_in_miss": llm_miss,
        "llm_cost_usd": round(llm_cost, 6),
        "llm_model": llm_recs[0].get("model", "") if llm_recs else "",
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
        if c == "jev":
            tin = sum(m.get("jev_in_tokens", 0) for m in ms)
            test = sum(m.get("jev_in_est", 0) for m in ms)
            tout = sum(m.get("jev_out_tokens", 0) for m in ms)
            cost = sum(m.get("jev_cost_usd", 0) for m in ms)
            tok = f"，输入 {tin:,} tokens" + (f" + 估算 {test:,}" if test else "")
            tok += f"，输出 {tout:,}（免费）"
            lines += ["", f"## {kind} 层开销", "",
                      f"- 总调用 {calls} 次，决策总延迟 {lat:.1f}s（平均 {lat / max(calls, 1):.2f}s/次）{tok}",
                      f"- 总成本 ${cost:.4f} ≈ ¥{cost * pricing.USD_TO_CNY:.3f}"
                      f"（单局 ${cost / max(len(ms), 1):.5f}，价格 $0.042/M 输入、输出免费）"]
        else:
            tin = sum(m.get("llm_in_tokens", 0) for m in ms)
            tout = sum(m.get("llm_out_tokens", 0) for m in ms)
            hit = sum(m.get("llm_in_hit", 0) for m in ms)
            miss = sum(m.get("llm_in_miss", 0) for m in ms)
            cost = sum(m.get("llm_cost_usd", 0) for m in ms)
            cache = f"（缓存命中 {hit:,} / 未命中 {miss:,}）" if hit or miss else ""
            model = next((m2.get("llm_model") for m2 in ms if m2.get("llm_model")), "")
            lines += ["", f"## {kind} 层开销（{model or 'deepseek-flash'}）", "",
                      f"- 总调用 {calls} 次，决策总延迟 {lat:.1f}s（平均 {lat / max(calls, 1):.2f}s/次）",
                      f"- 输入 {tin:,} tokens{cache}，输出 {tout:,} tokens",
                      f"- 总成本 ${cost:.4f} ≈ ¥{cost * pricing.USD_TO_CNY:.3f}"
                      f"（单局 ${cost / max(len(ms), 1):.5f}，高峰价；非高峰半价）"]

    # 成本对比行（两边都有数据时）
    if "jev" in cfgs and "llm" in cfgs:
        cj = sum(groups[(s, "jev")].get("jev_cost_usd", 0) for s in seeds) / len(seeds)
        cl = sum(groups[(s, "llm")].get("llm_cost_usd", 0) for s in seeds) / len(seeds)
        if cj > 0 and cl > 0:
            lines += ["", f"- **单局成本对比：LLM 是 Jev 的 {cl / cj:.1f} 倍**"
                      f"（Jev ¥{cj * pricing.USD_TO_CNY:.4f}/局 vs LLM ¥{cl * pricing.USD_TO_CNY:.3f}/局）"]

    lines += ["", "## 胜负计数（并列计胜）", ""] + [
        f"- {c}: {wins[c]} 局最深" for c in cfgs]
    text = "\n".join(lines)
    (LOGS / "ab_report.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(report())
