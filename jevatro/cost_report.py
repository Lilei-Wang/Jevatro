"""Token 消耗与成本对比报告：Jev vs DeepSeek LLM。

扫描 logs/ 下所有 run_jev_*.jsonl 与 run_llm_*.jsonl：
- 新日志（2026-09-22 起）每次调用落盘实测 in/out tokens 与 cost_usd；
- 旧日志缺 usage 的按文本长度粗估（明确标注"估算"），LLM 旧日志按
  token 数回溯计价（无缓存拆分，按全部未命中的保守口径）。
输出 logs/cost_report.md。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pricing

LOGS = Path(__file__).parent / "logs"


def _records(path: Path) -> list[dict]:
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return recs


def scan_runs() -> list[dict]:
    """返回每局一行的模型开销汇总。"""
    rows = []
    for path in sorted(LOGS.glob("run_*.jsonl")):
        kind = "jev" if "_jev_" in path.name else "llm" if "_llm_" in path.name else None
        if kind is None:
            continue
        recs = [r for r in _records(path) if r.get("kind") in ("jev", "llm")]
        if not recs:
            continue
        row = {
            "file": path.name, "kind": kind, "calls": len(recs),
            "latency": round(sum(r.get("latency", 0) for r in recs), 1),
            "in_real": 0, "out_real": 0, "in_est": 0,
            "hit": 0, "miss": 0, "cost_real": 0.0, "cost_back": 0.0,
            "model": recs[0].get("model", ""),
        }
        for r in recs:
            if r.get("cost_usd") is not None and r.get("in_tokens"):
                # 新日志：实测 token + 落盘成本
                row["in_real"] += r["in_tokens"]
                row["out_real"] += r.get("out_tokens", 0)
                row["hit"] += r.get("in_hit_tokens", 0)
                row["miss"] += r.get("in_miss_tokens", 0)
                row["cost_real"] += r.get("cost_usd", 0.0)
            elif kind == "llm":
                # 旧 LLM 日志：有 token 无成本 → 按 token 回溯计价（全未命中口径）
                in_t, out_t = r.get("in_tokens", 0), r.get("out_tokens", 0)
                model = r.get("model") or row["model"]
                if "glm" in model:            # 智谱免费档不计费
                    row["in_real"] += in_t
                    row["out_real"] += out_t
                else:
                    row["in_real"] += in_t
                    row["out_real"] += out_t
                    row["miss"] += in_t
                    row["cost_back"] += pricing.llm_cost_usd(in_t, 0, out_t, model=model)
            else:
                # 旧 Jev 日志：无 usage → 按文本长度粗估输入并折价
                q_txt = json.dumps(r.get("questions", {}), ensure_ascii=False)
                est = pricing.est_tokens(r.get("state", "") + q_txt)
                row["in_est"] += est
                row["cost_back"] += pricing.jev_cost_usd(est, 0)
        rows.append(row)
    return rows


def report() -> str:
    rows = scan_runs()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# Token 消耗与成本对比：Jev vs DeepSeek LLM", "",
             f"生成时间: {now}", ""]
    if not rows:
        return "\n".join(lines + ["（暂无 jev/llm 调用日志）"])

    lines += ["## 一、官方价格表", ""] + pricing.price_table_md() + [""]

    # ---- 总览 -------------------------------------------------------------
    def agg(kind):
        rs = [r for r in rows if r["kind"] == kind]
        n = len(rs)
        calls = sum(r["calls"] for r in rs)
        lat = sum(r["latency"] for r in rs)
        in_real = sum(r["in_real"] for r in rs)
        out_real = sum(r["out_real"] for r in rs)
        in_est = sum(r["in_est"] for r in rs)
        hit = sum(r["hit"] for r in rs)
        miss = sum(r["miss"] for r in rs)
        cost = sum(r["cost_real"] + r["cost_back"] for r in rs)
        return {"n": n, "calls": calls, "lat": lat, "in_real": in_real,
                "out_real": out_real, "in_est": in_est, "hit": hit, "miss": miss,
                "cost": cost}

    j, l = agg("jev"), agg("llm")
    lines += ["## 二、总消耗对比（全部历史对局累计）", "",
              "| 指标 | Jev (System One) | deepseek-flash (LLM) |",
              "|---|---|---|",
              f"| 对局数 | {j['n']} | {l['n']} |",
              f"| 决策调用次数 | {j['calls']} | {l['calls']} |",
              f"| 平均延迟/次 | {j['lat'] / max(j['calls'], 1):.2f}s | "
              f"{l['lat'] / max(l['calls'], 1):.2f}s |",
              f"| 输入 tokens（实测） | {j['in_real']:,} | {l['in_real']:,} |",
              f"| 输入 tokens（估算·旧日志） | {j['in_est']:,} | - |"]
    if l["hit"] or l["miss"]:
        lines.append(f"| 输入缓存命中/未命中 | - | {l['hit']:,} / {l['miss']:,} |")
    lines += [f"| 输出 tokens | {j['out_real']:,}（免费） | {l['out_real']:,} |",
              f"| 总成本（USD，高峰价） | ${j['cost']:.4f} | ${l['cost']:.4f} |",
              f"| 总成本（CNY 参考） | ¥{j['cost'] * pricing.USD_TO_CNY:.3f} | "
              f"¥{l['cost'] * pricing.USD_TO_CNY:.3f} |",
              f"| 单局成本（USD） | ${j['cost'] / max(j['n'], 1):.4f} | "
              f"${l['cost'] / max(l['n'], 1):.4f} |",
              "",
              "- Jev 旧日志无 API usage 返回，输入 tokens 按文本长度估算"
              "（0.93 字符/token，由 COST9 局 27 次实测调用校准），"
              "其成本 = (实测+估算) × $0.042/M；新日志直接使用 API 实测值。",
              "- LLM 旧日志按 token 数回溯计价（无缓存拆分，按全部未命中的保守口径）；"
              "glm-4-flash 免费档时期不计费。",
              ""]

    # ---- 每局明细 ---------------------------------------------------------
    lines += ["## 三、逐局明细", "",
              "| 对局日志 | 模型 | 调用 | 延迟合计(s) | in tokens | out tokens | 成本(USD) |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        in_t = f"{r['in_real']:,}" + (f" +{r['in_est']:,}估" if r["in_est"] else "")
        cost = r["cost_real"] + r["cost_back"]
        tag = "Jev" if r["kind"] == "jev" else "LLM"
        lines.append(f"| `{r['file']}` | {tag}·{r['model'] or '-'} | {r['calls']} | "
                     f"{r['latency']} | {in_t} | {r['out_real']:,} | ${cost:.4f} |")

    # ---- 最近一次同批对比的倍数 -------------------------------------------
    if j["calls"] and l["calls"]:
        per_j = (j["in_real"] + j["in_est"]) / max(j["calls"], 1)
        per_l = l["in_real"] / max(l["calls"], 1)
        cj, cl = j["cost"] / max(j["n"], 1), l["cost"] / max(l["n"], 1)
        lines += ["", "## 四、单次调用口径", "",
                  f"- Jev 单次调用输入 ≈ {per_j:,.0f} tokens（批量并行题），成本 ≈ "
                  f"${pricing.jev_cost_usd(per_j, 0):.5f}/次，输出免费",
                  f"- deepseek-flash 单次调用输入 ≈ {per_l:,.0f} tokens"
                  + (f"，其中缓存命中 {l['hit'] / max(l['calls'], 1):,.0f}" if l["hit"] else ""),
                  f"- 单局成本比 LLM/Jev ≈ {cl / max(cj, 1e-9):.1f} 倍"
                  f"（Jev ¥{cj * pricing.USD_TO_CNY:.4f} vs LLM ¥{cl * pricing.USD_TO_CNY:.3f}）"]

    text = "\n".join(lines)
    (LOGS / "cost_report.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(report())
