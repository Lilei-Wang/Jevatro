"""决策点对齐对比（第 3 层严格对照）：同种子、分叉前的同一商店，Jev vs LLM 各自买了什么。

原理：同种子 → 两臂的商店 1 完全相同；从第一次决策不同起 RNG 分叉、货架开始不同。
本工具按商店序号顺序对齐两臂的货架签名（商品key+价格集合），签名一致 = 未分叉 = 可比。

用法: python decision_bench.py          # 扫描全部历史日志，输出 logs/decision_bench.md
"""
from __future__ import annotations

import glob
import io
import json
import re
import sys
from pathlib import Path

from card_zh import card_zh

LOGS = Path(__file__).parent / "logs"

_ITEM_Q = re.compile(r"商品\[([a-z0-9_]+)[,（(].*?, \$(\d+)\]")
_LLM_ITEM = re.compile(r"^\s+(item\d+|voucher\d+): ([a-z0-9_]+)[(:,:].*?\$(\d+)\s*$", re.M)
_SHOP_LINE = re.compile(r"\[商店\](.*)")
_BUY_KEY = re.compile(r"^([jcvp]_[a-z0-9_]+) value=")


def load(path: str) -> list[dict]:
    try:
        return [json.loads(l) for l in open(path, encoding="utf-8")]
    except OSError:
        return []


def seed_of(rows: list[dict]) -> str | None:
    for r in rows:
        if r.get("kind") == "game_start":
            return r.get("seed")
    return None


def jev_shop_visits(rows: list[dict]) -> list[dict]:
    """Jev 臂的商店决策点：jev 记录（含商品题）→ 货架签名 + 实际购买。"""
    visits = []
    jevs = [r for r in rows if r.get("kind") == "jev"]
    acts = [r for r in rows if r.get("kind") == "action"]
    for i, r in enumerate(jevs):
        items = {}
        for k, q in (r.get("questions") or {}).items():
            m = re.match(r"^(item\d+|voucher\d+)__synergy$", k)
            if m:
                mm = _ITEM_Q.match(str(q))
                if mm:
                    items[m.group(1)] = (mm.group(1), int(mm.group(2)))
        if not items:
            continue
        nxt_t = jevs[i + 1].get("t", 1e9) if i + 1 < len(jevs) else 1e9
        bought = []
        for a in acts:
            if not (r["t"] <= a.get("t", -1) < nxt_t) or a.get("method") != "buy":
                continue
            why = str((a.get("params") or {}).get("extra", {}).get("why", ""))
            mm = _BUY_KEY.match(why)
            if mm:
                bought.append(mm.group(1))
        visits.append({"t": r["t"], "items": items, "bought": bought})
    return visits


def llm_shop_visits(rows: list[dict]) -> list[dict]:
    """LLM 臂的商店决策点：prompt 含"可选购买项"的 llm 记录 → 货架签名 + 回复购买。"""
    visits = []
    for r in rows:
        if r.get("kind") != "llm" or "可选购买项" not in str(r.get("prompt", "")):
            continue
        prompt = str(r.get("prompt", ""))
        items = {}
        for slot, key, price in _LLM_ITEM.findall(prompt):
            items[slot] = (key, int(price))
        if not items:
            continue
        bought, reason, ok = [], "", True
        try:
            m = re.search(r"\{.*\}", r.get("reply") or "", re.S)
            j = json.loads(m.group(0)) if m else {}
            reason = j.get("reason", "")
            slot2key = {s: k for s, (k, _p) in items.items()}
            bought = [slot2key.get(b, b) for b in j.get("buys", [])]
        except Exception:
            ok = False
        visits.append({"t": r["t"], "items": items, "bought": bought,
                       "reason": reason, "ok": ok})
    return visits


def sig(v: dict) -> tuple:
    return tuple(sorted((k, p) for k, p in v["items"].values()))


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    jev_runs: dict[str, list] = {}
    llm_runs: dict[str, list] = {}
    for f in glob.glob(str(LOGS / "run_jev_*.jsonl")):
        rows = load(f)
        s = seed_of(rows)
        if s and "shelf_has_goods" in str(rows):   # 只取新代码日志（题型含货架存在性）
            jev_runs.setdefault(s, []).extend(jev_shop_visits(rows))
    for f in glob.glob(str(LOGS / "run_llm_*.jsonl")):
        rows = load(f)
        s = seed_of(rows)
        if s:
            llm_runs.setdefault(s, []).extend(llm_shop_visits(rows))

    lines = ["# 决策点对齐对比：Jev vs LLM（同种子 · 分叉前）", "",
             "原理：同种子商店1完全相同；首次决策不同后货架分叉即停止对齐。", ""]
    n_pts = n_agree = 0
    jev_buys = llm_buys = llm_fail = 0
    for seed in sorted(set(jev_runs) & set(llm_runs)):
        js, ls = jev_runs[seed], llm_runs[seed]
        rows_out = []
        for k, (jv, lv) in enumerate(zip(js, ls)):
            if sig(jv) != sig(lv):
                rows_out.append(f"| {k+1} | （货架已分叉，对齐终止） | | | |")
                break
            n_pts += 1
            jk, lk = set(jv["bought"]), set(lv["bought"])
            agree = jk == lk
            n_agree += agree
            jev_buys += len(jk)
            llm_buys += len(lk)
            llm_fail += (not lv.get("ok", True)) * 1
            shelf = "、".join(f"{card_zh(k2)}${p}" for k2, p in sig(jv)[:4])
            jtxt = "、".join(card_zh(x) for x in jk) or "不买"
            ltxt = ("、".join(card_zh(x) for x in lk) or "不买") + \
                   (f"（{lv['reason'][:18]}）" if lv.get("reason") else "")
            if not lv.get("ok", True):
                ltxt = "❌回复解析失败→回退"
            rows_out.append(f"| {k+1} | {shelf} | {jtxt} | {ltxt} | {'✓' if agree else '✗'} |")
        if rows_out:
            lines += [f"## 种子 {seed}", "",
                      "| 商店# | 货架(前4) | 🃏 Jev 购买 | 🤖 LLM 购买(理由) | 一致 |",
                      "|---|---|---|---|---|"] + rows_out + [""]
    lines += ["## 汇总", "",
              f"- 对齐决策点：**{n_pts}** 个（分叉前）",
              f"- 决策一致率：**{n_agree}/{n_pts}**" + (f" = {100*n_agree/max(n_pts,1):.0f}%" if n_pts else ""),
              f"- Jev 购买 {jev_buys} 件 vs LLM 购买 {llm_buys} 件"
              f"（LLM 解析失败 {llm_fail} 次）"]
    out = LOGS / "decision_bench.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[-5:]))
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
