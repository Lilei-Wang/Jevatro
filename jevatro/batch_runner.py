"""多种子 A/B 批量对比：naive（solver-only）vs jev（solver+Jev）。

用法: python batch_runner.py [种子数]     # 默认 5 个种子（JEVATRO1..N）
前提: 带 balatrobot 的游戏运行中。输出 logs/batch_summary.md + JSON。
说明: 检测到游戏冻结（UI 事件循环停摆）时自动重启游戏自愈后继续。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import jev_bot
import llm_bot
import naive_bot
from client import BalatroClient

LOGS = Path(__file__).parent / "logs"
GAME_EXE = r"D:\software\Steam\steamapps\common\Balatro\Balatro.exe"

CONFIGS = (
    ("naive", "A/B 基线", naive_bot),
    ("jev", "solver+Jev", jev_bot),
    ("llm", "solver+LLM", llm_bot),
)


def restart_game() -> bool:
    """强杀并重启游戏（冻结自愈），等待 API 上线后置顶窗口+高优先级（防后台遮挡停摆）。"""
    print("[heal] 游戏冻结，重启游戏…", flush=True)
    subprocess.run(["taskkill", "/im", "Balatro.exe", "/f"], capture_output=True)
    time.sleep(4)
    os.startfile(GAME_EXE)  # noqa: P101
    bot = BalatroClient()
    ok = bot.wait_online(tries=40, delay=2.0)
    if ok:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(Path(__file__).parent / "boost_game.ps1")],
                       capture_output=True)
    return ok


def batch(n_seeds: int = 5, repeats: int = 1) -> list[dict]:
    rows = []
    seeds = [f"JEVATRO{i}" for i in range(1, n_seeds + 1)]
    for seed in seeds:
        for rep in range(1, repeats + 1):
            for tag, _label, run in CONFIGS:
                label = f"{seed}{' · #'+str(rep) if repeats > 1 else ''}"
                print(f"\n===== {label} · {tag} =====", flush=True)
                t0 = time.time()
                try:
                    gs = run.run(seed=seed)
                    rows.append({
                        "seed": seed, "config": tag, "rep": rep,
                        "won": gs.get("won"), "ante": gs.get("ante_num"),
                        "round": gs.get("round_num"),
                        "money": gs.get("money"), "n_jokers": (gs.get("jokers") or {}).get("count"),
                        "wall_s": round(time.time() - t0, 1),
                    })
                except (Exception, SystemExit) as e:  # 单局崩溃/退出不炸整批
                    rows.append({"seed": seed, "config": tag, "rep": rep,
                                 "error": f"{type(e).__name__}: {e}"})
                    import traceback
                    traceback.print_exc()
                # 冻结自愈：该局因游戏 UI 停摆而放弃 → 重启游戏
                if getattr(run, "last_frozen", False):
                    rows.append({"seed": seed, "config": tag, "rep": rep,
                                 "error": "frozen(已重启游戏)"})
                    if not restart_game():
                        print("[fatal] 游戏重启失败，终止批量", flush=True)
                        break
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
        rep = f"#{r.get('rep', 1)}" if any(x.get("rep", 1) > 1 for x in rows if x.get("rep")) else ""
        lines.append(
            f"| {r['seed']}{rep} | {r['config']} | "
            f"{'🏆胜' if r.get('won') else '💀败'} | {r.get('ante','-')} | "
            f"{r.get('round','-')} | {r.get('money','-')} | {r.get('n_jokers','-')} | "
            f"{r.get('wall_s','-')} |")

    # ---- 聚合统计：均值/标准差 + 成对胜负 + 臂内噪声 ----
    import statistics as st
    lines += ["", "## 聚合统计", ""]
    agg = {}
    for cfg in ("naive", "jev", "llm"):
        sub = [r["ante"] for r in rows if r["config"] == cfg and "ante" in r]
        if sub:
            sd = st.stdev(sub) if len(sub) > 1 else 0.0
            wins = sum(1 for r in rows if r["config"] == cfg and r.get("won"))
            agg[cfg] = sub
            lines.append(f"- **{cfg}**: 平均 Ante **{sum(sub)/len(sub):.2f}** ±{sd:.2f}"
                         f"（n={len(sub)}，最深 {max(sub)}，通关 {wins}）")
    # 成对比较（同种子首 repeat 对齐）
    if "jev" in agg and "naive" in agg:
        pairs = []
        for seed in {r["seed"] for r in rows}:
            def first(cfg):
                v = [r["ante"] for r in rows
                     if r["seed"] == seed and r["config"] == cfg
                     and "ante" in r and r.get("rep", 1) == 1]
                return v[0] if v else None
            jv, nv = first("jev"), first("naive")
            if jv is not None and nv is not None:
                pairs.append((seed, jv, nv))
        if pairs:
            w = sum(1 for _, j, n in pairs if j > n)
            l = sum(1 for _, j, n in pairs if j < n)
            t = len(pairs) - w - l
            lines.append(f"\n**成对胜负 (jev vs naive, 同种子)**: jev 胜 {w} / 负 {l} / 平 {t}"
                         f"（{len(pairs)} 对）")
    # 臂内噪声（同种子多次 repeat 的极差）
    rep_noise = {}
    for cfg in ("naive", "jev", "llm"):
        spread = []
        for seed in {r["seed"] for r in rows}:
            v = [r["ante"] for r in rows
                 if r["seed"] == seed and r["config"] == cfg and "ante" in r]
            if len(v) > 1:
                spread.append(max(v) - min(v))
        if spread:
            rep_noise[cfg] = sum(spread) / len(spread)
            lines.append(f"- **{cfg} 臂内噪声**: 同种子重复平均极差 {rep_noise[cfg]:.2f} Ante"
                         f"（{len(spread)} 个种子有重复）")
    if rep_noise:
        lines.append("\n> 结论判据：臂间均值差需显著大于臂内噪声才能下结论。")
    text = "\n".join(lines)
    (LOGS / "batch_summary.md").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    rep = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    batch(n, rep)
