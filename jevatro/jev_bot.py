"""jev bot：Tier 0 求解器出牌 + Tier 1 Jev 商店/盲注决策。

用法: python jev_bot.py [seed]
前提: 带 balatrobot 的游戏运行中 + jevatro/.env 配置 TYPESAFE_API_KEY。
"""
from __future__ import annotations

import sys
import time

from client import BalatroClient, BalatroError
from jev_layer import JevLayer
from logger import RunLogger
from naive_bot import act
from solver import best_play, best_discard

MAX_ACTIONS = 4000
REROLL_PER_SHOP = 2


def use_planets(bot, log, gs: dict) -> dict:
    """把消耗区的 Planet 立即用掉（升级牌型，无需目标）。"""
    attempts = len(gs.get("consumables", {}).get("cards", [])) + 1
    while gs.get("state") == "SHOP" and attempts > 0:
        attempts -= 1
        cons = gs.get("consumables", {}).get("cards", [])
        idx = next((i for i, c in enumerate(cons) if c.get("set") == "PLANET"), None)
        if idx is None:
            break
        gs = act(bot, log, gs, "use", consumable=idx)
        time.sleep(0.2)
    return gs


def run(seed: str | None = None, deck: str = "RED", stake: str = "WHITE") -> dict:
    bot = BalatroClient()
    if not bot.wait_online(tries=5):
        raise SystemExit("balatrobot 不可达：请先启动带 mod 的 Balatro")
    log = RunLogger("jev")
    jev = JevLayer(log)

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
    while n < MAX_ACTIONS:
        n += 1
        state = gs.get("state")

        if state == "GAME_OVER":
            break
        elif state == "BLIND_SELECT":
            action, why = jev.blind_decision(gs)
            gs = act(bot, log, gs, action, extra={"why": why})
            print(f"  [blind] {action} ({why})")
        elif state == "SELECTING_HAND":
            bp = best_play(gs)
            # 打不过且有弃牌余量：先挖牌（保方向弃边缘），两手以上才值得弃
            if (not bp["can_clear"]
                    and gs.get("round", {}).get("discards_left", 0) > 0
                    and gs.get("round", {}).get("hands_left", 0) >= 2):
                d = best_discard(gs)
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
            rerolls = 0
            while gs.get("state") == "SHOP" and rerolls <= REROLL_PER_SHOP:
                plan = jev.shop_plan(gs)
                if not plan:
                    break
                step = plan[0]
                gs = act(bot, log, gs, step["method"], extra={"why": step.get("why")}, **step["params"])
                print(f"  [shop] {step['method']} {step['params']} ({step.get('why')})")
                if step["method"] == "reroll":
                    rerolls += 1
                time.sleep(0.2)
            gs = use_planets(bot, log, gs)
            gs = act(bot, log, gs, "next_round")
        elif state == "SMODS_BOOSTER_OPENED":
            gs = act(bot, log, gs, "pack", skip=True)
        else:
            time.sleep(0.5)
            gs = bot.gamestate()
        time.sleep(0.1)

    log.finish(gs)
    print(f"[end] won={gs.get('won')} ante={gs.get('ante_num')} round={gs.get('round_num')} "
          f"actions={log.actions} illegal={log.illegal} "
          f"jev_calls={jev.calls} jev_latency={jev.total_latency:.1f}s jev_failed={jev.failed} "
          f"log={log.path}")
    return gs


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
