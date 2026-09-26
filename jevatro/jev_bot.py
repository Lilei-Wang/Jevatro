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
from naive_bot import act, _sig
from solver import best_play, best_discard
import use_policy

MAX_ACTIONS = 4000
REROLL_PER_SHOP = 2


def _shop_sig(gs: dict) -> tuple:
    shop = gs.get("shop") or {}
    return (gs.get("money"), (gs.get("jokers") or {}).get("count"),
            tuple(sorted((c.get("key"), c.get("cost", {}).get("buy"))
                         for c in shop.get("cards", []))))


def run(seed: str | None = None, deck: str = "RED", stake: str = "WHITE") -> dict:
    run.last_frozen = False
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
            action, why = jev.blind_decision(gs)
            gs = act(bot, log, gs, action, extra={"why": why})
            print(f"  [blind] {action} ({why})")
        elif state == "SELECTING_HAND":
            # 先把需要手牌目标的消耗牌用掉（强化最佳卡/转花色/瘦身等）
            gs = use_policy.apply(bot, log, gs, phase="HAND")
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
            # 槽满先用：消耗牌满员时先用掉可安全使用的牌腾位，再看商店（魔典原则）
            cons = gs.get("consumables", {})
            if cons.get("count", 0) >= cons.get("limit", 2):
                gs = use_policy.apply(bot, log, gs, phase="SHOP", max_uses=1)
            rerolls = 0
            fails = 0
            # 迭代13实测回退：富裕时重掷预算加倍无效（死钱不降，DEMW4反-1）——
            # 预算不是瓶颈，Jev 的重掷 Noul 判断（~0.5 阈值）本身保守，加了预算也不掷
            while gs.get("state") == "SHOP" and rerolls <= REROLL_PER_SHOP and fails < 2:
                sig = _shop_sig(gs)
                plan = jev.shop_plan(gs)
                if not plan:
                    break
                rerolled = False
                for step in plan:
                    if gs.get("state") != "SHOP":
                        break
                    gs = act(bot, log, gs, step["method"], extra={"why": step.get("why")}, **step["params"])
                    print(f"  [shop] {step['method']} {step['params']} ({step.get('why')})")
                    if step["method"] == "reroll":
                        rerolls += 1
                        rerolled = True
                    time.sleep(0.2)
                # 买入后重新规划（每计划限一张防索引位移）；签名不变=无进展，防死循环
                if not rerolled and _shop_sig(gs) == sig:
                    fails += 1
                else:
                    fails = 0
            gs = use_policy.apply(bot, log, gs, phase="SHOP")  # 星球/金钱塔罗等
            gs = act(bot, log, gs, "next_round")
        elif state == "SMODS_BOOSTER_OPENED":
            idx, why = jev.pack_pick(gs)
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
          f"jev_calls={jev.calls} jev_latency={jev.total_latency:.1f}s jev_failed={jev.failed} "
          f"log={log.path}")
    return gs


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
