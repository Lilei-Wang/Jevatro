"""naive bot（配置 A+）：求解器出牌 + 朴素商店策略，打完整局。

用法: python naive_bot.py [seed]
前提: 游戏已带 balatrobot mod 运行中（127.0.0.1:12346）。
"""
from __future__ import annotations

import sys
import time

from client import BalatroClient, BalatroError
from logger import RunLogger
from solver import best_play, best_discard

MAX_ACTIONS = 4000


def act(bot, log, before: dict, method: str, raise_on_error: bool = False, **params) -> dict:
    """执行动作并记录；默认失败时返回当前 gamestate 而不是崩掉。

    "buttons not ready"（发牌动画竞态）自动等待重试。
    """
    for attempt in range(9):
        try:
            after = bot.call(method, **params)
            log.action(method, params, before, after)
            return after
        except BalatroError as e:
            if "not ready" in str(e) and attempt < 8:
                time.sleep(0.6)
                continue
            after = bot.gamestate()
            log.action(method, params, before, after, error=str(e))
            if raise_on_error:
                raise
            return after
    return bot.gamestate()


def shop_policy(gs: dict) -> list[tuple[str, dict]]:
    """朴素商店策略：买得起的第一张小丑（有空位时）→ 买得起的第一张兑换券。"""
    actions: list[tuple[str, dict]] = []
    money = gs.get("money", 0)
    shop = gs.get("shop", {}).get("cards", [])
    jokers = gs.get("jokers", {})
    has_joker_slot = jokers.get("count", 0) < jokers.get("limit", 5)

    if has_joker_slot:
        for i, card in enumerate(shop):
            if card.get("set") == "JOKER" and card.get("cost", {}).get("buy", 999) <= money:
                actions.append(("buy", {"card": i}))
                break
    for i, card in enumerate(shop):
        if card.get("set") == "VOUCHER" and card.get("cost", {}).get("buy", 999) <= money:
            actions.append(("buy", {"voucher": i}))
            break
    return actions


def run(seed: str | None = None, deck: str = "RED", stake: str = "WHITE") -> dict:
    bot = BalatroClient()
    if not bot.wait_online(tries=5):
        raise SystemExit("balatrobot 不可达：请先启动带 mod 的 Balatro")
    log = RunLogger("naive")

    gs = bot.gamestate()
    log.log("boot", boot_state=gs.get("state"))

    if gs.get("state") != "MENU":
        gs = act(bot, log, gs, "menu")

    params = {"deck": deck, "stake": stake}
    if seed:
        params["seed"] = seed
    gs = act(bot, log, gs, "start", **params)
    log.log("game_start", seed=gs.get("seed"), deck=deck, stake=stake)
    print(f"[start] seed={gs.get('seed')}")

    n = 0
    while n < MAX_ACTIONS:
        n += 1
        state = gs.get("state")

        if state == "GAME_OVER":
            break
        elif state == "BLIND_SELECT":
            gs = act(bot, log, gs, "select")
        elif state == "SELECTING_HAND":
            bp = best_play(gs)
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
            while gs.get("state") == "SHOP":
                plan = shop_policy(gs)
                if not plan:
                    break
                method, p = plan[0]
                gs = act(bot, log, gs, method, **p)
                time.sleep(0.2)
            gs = act(bot, log, gs, "next_round")
        elif state == "SMODS_BOOSTER_OPENED":
            gs = act(bot, log, gs, "pack", skip=True)
        else:
            time.sleep(0.5)
            gs = bot.gamestate()
        time.sleep(0.1)

    log.finish(gs)
    won = gs.get("won")
    print(f"[end] won={won} ante={gs.get('ante_num')} round={gs.get('round_num')} "
          f"actions={log.actions} illegal={log.illegal} log={log.path}")
    return gs


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
