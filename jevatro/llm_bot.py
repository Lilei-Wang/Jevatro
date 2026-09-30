"""llm bot：Tier 0 求解器出牌 + 传统 LLM（智谱 GLM）商店/盲注/开包决策。

用法: python llm_bot.py [seed]
与 jev_bot 完全同构，唯一差异是决策层换成 LlmLayer（公平 A/B）。
"""
from __future__ import annotations

import sys
import time

from client import BalatroClient, BalatroError
from llm_layer import LlmLayer
from logger import RunLogger
from naive_bot import act, _sig
from solver import best_play, best_discard
import use_policy

MAX_ACTIONS = 4000
REROLL_PER_SHOP = 0  # LLM 层不重掷（保持决策面一致）


def run(seed: str | None = None, deck: str = "RED", stake: str = "WHITE") -> dict:
    run.last_frozen = False
    bot = BalatroClient()
    if not bot.wait_online(tries=5):
        raise SystemExit("balatrobot 不可达：请先启动带 mod 的 Balatro")
    log = RunLogger("llm")
    llm = LlmLayer(log)

    gs = bot.gamestate()
    log.log("boot", boot_state=gs.get("state"))
    if gs.get("state") != "MENU":
        gs = act(bot, log, gs, "menu")

    params = {"deck": deck, "stake": stake}
    if seed:
        params["seed"] = seed
    for attempt in range(3):
        gs = act(bot, log, gs, "start", **params)
        if gs.get("state") != "MENU":
            break
        print(f"[warn] start 失败(第{attempt + 1}次)，重试…")
        time.sleep(2)
    if gs.get("state") == "MENU":
        raise SystemExit("start 连续失败，退出（见日志 error 字段）")
    log.log("game_start", seed=gs.get("seed"), deck=deck, stake=stake)
    print(f"[start] seed={gs.get('seed')}")

    n = 0
    stuck = 0
    prev_sig = None
    while n < MAX_ACTIONS:
        n += 1
        state = gs.get("state")

        cur_sig = _sig(gs)
        stuck = stuck + 1 if cur_sig == prev_sig else 0
        prev_sig = cur_sig
        if stuck >= 8:
            log.log("frozen", sig=cur_sig, actions=n)
            print(f"[frozen] 状态连续 {stuck} 轮无进展，放弃本局")
            run.last_frozen = True
            break

        if state == "GAME_OVER":
            break
        elif state == "BLIND_SELECT":
            action, why = llm.blind_decision(gs)
            gs = act(bot, log, gs, action, extra={"why": why})
            print(f"  [blind] {action} ({why})")
        elif state == "SELECTING_HAND":
            gs = use_policy.apply(bot, log, gs, phase="HAND")
            bp = best_play(gs)
            if (not bp["can_clear"]
                    and gs.get("round", {}).get("discards_left", 0) > 0
                    and gs.get("round", {}).get("hands_left", 0) >= 2):
                d, dwhy = best_discard(gs)
                if d:
                    gs = act(bot, log, gs, "discard", cards=d,
                             extra={"why": f"dig: best={bp['total']:.0f}/need={bp['need']}"})
                    print(f"  [ante {gs.get('ante_num')} r{gs.get('round_num')}] "
                          f"discard {d} (best={bp['total']:.0f} < {bp['need']})")
                    time.sleep(0.1)
                    continue
            try:
                gs = act(bot, log, gs, "play", raise_on_error=True, cards=bp["indices"],
                         extra={"solver": {k: bp[k] for k in ("hand", "chips", "mult", "total")}})
            except BalatroError as e:
                hand_n = len(gs.get("hand", {}).get("cards", []))
                gs = act(bot, log, gs, "play", cards=list(range(min(5, hand_n))),
                         extra={"solver_fallback": str(e)})
            print(f"  [ante {gs.get('ante_num')} r{gs.get('round_num')}] "
                  f"play {bp['hand']} = {bp['total']:.0f}")
        elif state == "ROUND_EVAL":
            gs = act(bot, log, gs, "cash_out")
        elif state == "SHOP":
            fails = 0
            while gs.get("state") == "SHOP" and fails < 2:
                sig = (gs.get("money"), (gs.get("jokers") or {}).get("count"),
                       tuple(sorted((c.get("key"), c.get("cost", {}).get("buy"))
                                    for c in (gs.get("shop") or {}).get("cards", []))))
                plan = llm.shop_plan(gs)
                if not plan:
                    break
                for step in plan:
                    if gs.get("state") != "SHOP":
                        break
                    gs = act(bot, log, gs, step["method"], extra={"why": step.get("why")},
                             **step["params"])
                    print(f"  [shop] {step['method']} {step['params']} ({step.get('why')})")
                    time.sleep(0.2)
                if sig == (gs.get("money"), (gs.get("jokers") or {}).get("count"),
                           tuple(sorted((c.get("key"), c.get("cost", {}).get("buy"))
                                        for c in (gs.get("shop") or {}).get("cards", [])))):
                    fails += 1
                else:
                    fails = 0
            gs = use_policy.apply(bot, log, gs, phase="SHOP")
            gs = act(bot, log, gs, "next_round")
        elif state == "SMODS_BOOSTER_OPENED":
            idx, why = llm.pack_pick(gs)
            if idx is not None:
                gs = act(bot, log, gs, "pack", card=idx, extra={"why": why})
            else:
                gs = act(bot, log, gs, "pack", skip=True, extra={"why": why})
        else:
            time.sleep(0.5)
            gs = bot.gamestate()
        time.sleep(0.1)

    log.finish(gs)
    print(f"[end] won={gs.get('won')} ante={gs.get('ante_num')} round={gs.get('round_num')} "
          f"actions={log.actions} illegal={log.illegal} "
          f"llm_calls={llm.calls} llm_latency={llm.total_latency:.1f}s "
          f"tokens={llm.in_tokens}in/{llm.out_tokens}out llm_failed={llm.failed} "
          f"log={log.path}")
    return gs


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
