"""消耗牌使用策略（星球/塔罗/幻灵）。

原则：只实现"目标明确、无副作用风险"的用法；无法安全使用的卡不买（NO_BUY）。
使用时机：SHOP（无目标类+金钱类）、SELECTING_HAND（需要选目标类）。
"""
from __future__ import annotations

import time

from client import BalatroError
from solver import best_play

# 各卡的用法：none=直接用 / money=有钱才用 / best2|best1=强化最优出牌的计分卡
# junk2=弃掉两张边缘牌 / offsuit3=转主花色 / strength2=升最常见点数 / seal1=最佳卡加印
USE_POLICY: dict[str, str] = {
    # 星球（无目标）
    "c_mercury": "none", "c_venus": "none", "c_earth": "none", "c_mars": "none",
    "c_jupiter": "none", "c_saturn": "none", "c_uranus": "none", "c_neptune": "none",
    "c_pluto": "none", "c_planet_x": "none", "c_ceres": "none", "c_eris": "none",
    "c_black_hole": "none",
    # 塔罗：生成/无目标（槽位守卫见 _blocked：judgement 需空小丑槽，
    # fool/emperor/high_priestess 需空消耗槽，否则 API 拒绝 NOT_ALLOWED）
    "c_fool": "none", "c_high_priestess": "none", "c_emperor": "none",
    "c_judgement": "none", "c_wheel_of_fortune": "none",
    # 塔罗：金钱
    "c_hermit": "money", "c_temperance": "money",
    # 塔罗：强化（H5 修复：真实 key 是 c_heirophant，旧拼写导致买入后永不可用）
    "c_magician": "best2", "c_empress": "best2", "c_heirophant": "best2",
    "c_lovers": "best1", "c_chariot": "best1", "c_justice": "best1",
    "c_devil": "best1", "c_tower": "best1", "c_cryptid": "best1",
    # 塔罗：转花色 / 升点 / 毁灭
    "c_star": "offsuit3", "c_moon": "offsuit3", "c_sun": "offsuit3", "c_world": "offsuit3",
    "c_strength": "strength2", "c_hanged_man": "junk2",
    # 幻灵：印记/版本（目标最佳卡）/ 无目标类
    "c_talisman": "seal1", "c_deja_vu": "seal1", "c_trance": "seal1",
    "c_medium": "seal1", "c_aura": "seal1",
    # M1：familiar/grim/incantation 效果是"毁手中1张随机牌换强化牌"——
    # 商店阶段无手牌必报错，只应在 SELECTING_HAND 用（hand_none）
    "c_familiar": "hand_none", "c_grim": "hand_none", "c_incantation": "hand_none",
    "c_soul": "none",
}

# 不买：无安全用法或副作用大（Death复制/Sigil全手随机花色/Ouija减手牌位/
# Ectoplasm减手牌位/Immolate毁5张）
# M2 条件解禁：Ankh/Hex 在场上仅 1 小丑时无副作用（复制/镀彩唯一小丑）；
# Wraith 清钱换稀有 Joker，钱少时利息损失可忽略。
NO_BUY = {
    "c_death", "c_sigil", "c_ouija", "c_ectoplasm", "c_immolate",
    "c_ankh", "c_wraith", "c_hex",
}
NO_BUY_CONDITIONAL = {   # 满足条件时可买/可用（见 buy_ok / _blocked）
    "c_ankh":   lambda gs: len((gs.get("jokers") or {}).get("cards", [])) == 1,
    "c_hex":    lambda gs: len((gs.get("jokers") or {}).get("cards", [])) == 1,
    "c_wraith": lambda gs: gs.get("money", 0) <= 8,
}


def buy_ok(key: str, gs: dict) -> bool:
    """购买/开包候选过滤：NO_BUY 但满足条件解禁的放行。"""
    if key not in NO_BUY:
        return True
    cond = NO_BUY_CONDITIONAL.get(key)
    return bool(cond and cond(gs))


SHOP_USABLE = {"none", "money"}          # SHOP 状态可用的类型
HAND_USABLE = {"best1", "best2", "junk2", "offsuit3", "strength2", "seal1",
               "hand_none"}
# 需要选目标的类型（hand_none 无目标直接用）
TARGETED = HAND_USABLE - {"hand_none"}


def _blocked(gs: dict, key: str) -> bool:
    """H6 生成类守卫：生成物需要空槽，否则游戏返回 NOT_ALLOWED（实测 20 次）。"""
    cons = gs.get("consumables") or {}
    jok = gs.get("jokers") or {}
    if key == "c_judgement":          # 生成随机小丑 → 需空小丑槽
        return jok.get("count", 0) >= jok.get("limit", 5)
    if key in ("c_fool", "c_emperor", "c_high_priestess"):
        return cons.get("count", 0) >= cons.get("limit", 2)
    cond = NO_BUY_CONDITIONAL.get(key)
    if key in NO_BUY and cond:        # ankh/hex/wraith 条件不满足时也不可用
        return not cond(gs)
    return False


def _best_indices(gs: dict, n: int) -> list[int]:
    """最优出牌的计分卡（按出牌组合原索引），取前 n 张。

    R18.6 钢K流支持：持有 Baron 时，强化/印记目标优先 K——
    K 是要攥在手里的倍率源，给 K 上钢/红印才是引擎件。
    """
    jkeys = {j.get("key") for j in (gs.get("jokers") or {}).get("cards", [])}
    if "j_baron" in jkeys:
        kings = [i for i, c in enumerate(gs["hand"]["cards"])
                 if c["value"]["rank"] == "K"]
        if len(kings) >= n:
            return kings[:n]
    bp = best_play(gs)
    hand = gs["hand"]["cards"]
    from scoring import evaluate_hand
    played = [hand[i] for i in bp["indices"]]
    _, scoring_idx = evaluate_hand(played)
    order = [bp["indices"][i] for i in scoring_idx]
    return order[:n]


def _offsuit_targets(gs: dict, want_suit: str) -> list[int]:
    """把不在主花色的牌转过去（≤3张）。主花色=最优出牌组合里最多的花色。"""
    bp = best_play(gs)
    hand = gs["hand"]["cards"]
    combo = [hand[i] for i in bp["indices"]]
    suits = [c["value"]["suit"] for c in combo]
    if not suits:
        return []
    dom = max(set(suits), key=suits.count)
    if want_suit != dom:
        return []  # 塔罗花色与构筑方向不符，留给下一次
    out = [i for i, c in enumerate(hand) if c["value"]["suit"] != dom][:3]
    return out


def _strength_targets(gs: dict) -> list[int]:
    """最优组合里出现≥2次的点数升 1 级（对子→三条方向）。"""
    bp = best_play(gs)
    hand = gs["hand"]["cards"]
    combo = [hand[i] for i in bp["indices"]]
    ranks = [c["value"]["rank"] for c in combo]
    if not ranks:
        return []
    dom = max(set(ranks), key=ranks.count)
    if ranks.count(dom) < 2:
        return []
    return [bp["indices"][k] for k, c in enumerate(combo) if c["value"]["rank"] == dom][:2]


def _junk_targets(gs: dict) -> list[int]:
    """不在最优组合且不符合方向的牌（毁灭瘦身）。"""
    bp = best_play(gs)
    keep = set(bp["indices"])
    hand = gs["hand"]["cards"]
    combo = [hand[i] for i in bp["indices"]]
    suits = [c["value"]["suit"] for c in combo]
    ranks = [c["value"]["rank"] for c in combo]
    dom_s = max(set(suits), key=suits.count) if suits else None
    dom_r = max(set(ranks), key=ranks.count) if ranks else None
    for i, c in enumerate(hand):
        if i in keep:
            continue
        if dom_s and c["value"]["suit"] == dom_s:
            keep.add(i)
        elif dom_r and c["value"]["rank"] == dom_r:
            keep.add(i)
    return [i for i in range(len(hand)) if i not in keep][:2]


def _targets_for(gs: dict, kind: str, key: str) -> list[int] | None:
    if kind == "best2":
        return _best_indices(gs, 2)
    if kind == "best1":
        return _best_indices(gs, 1)
    if kind == "seal1":
        return _best_indices(gs, 1)
    if kind == "junk2":
        return _junk_targets(gs)
    if kind == "strength2":
        return _strength_targets(gs)
    if kind == "offsuit3":
        suit = {"c_star": "D", "c_moon": "C", "c_sun": "H", "c_world": "S"}[key]
        return _offsuit_targets(gs, suit)
    return None


def apply(bot, log, gs: dict, phase: str, max_uses: int = 4) -> dict:
    """在给定 phase（SHOP / HAND）把能用掉的消耗牌用掉。返回最新 gamestate。"""
    usable = SHOP_USABLE if phase == "SHOP" else HAND_USABLE
    uses = 0
    fails = 0
    skipped: set[str] = set()
    while gs.get("state") in ("SHOP", "SELECTING_HAND") and uses < max_uses and fails < 2:
        cons = gs.get("consumables", {}).get("cards", [])
        picked = None
        for i, c in enumerate(cons):
            if c.get("key") in skipped:
                continue
            key = c.get("key", "")
            kind = USE_POLICY.get(key)
            if kind in usable and not _blocked(gs, key):
                picked = (i, c, kind)
                break
        if picked is None:
            break
        i, card, kind = picked
        if kind == "money" and gs.get("money", 0) < 8:
            skipped.add(card["key"])  # 钱少暂不用，看下一张
            continue
        params = {"consumable": i}
        tg = _targets_for(gs, kind, card["key"])
        if kind in TARGETED:
            if not tg:
                fails += 1
                skipped.add(card["key"])  # 无合适目标 → 本回合跳过这张
                continue
            params["cards"] = tg
        try:
            before = gs
            gs = bot.call("use", **params)
            log.action("use", params, before, gs,
                       extra={"why": f"{card['key']} ({kind})"})
            uses += 1
            print(f"  [use] {card['key']} ({kind})" + (f" -> cards {tg}" if tg else ""))
        except BalatroError as e:
            log.action("use", params, gs, bot.gamestate(), error=str(e),
                       extra={"why": f"{card['key']} ({kind})"})
            fails += 1
            skipped.add(card["key"])  # H6：失败不再重试同一张（防连败殃及同批）
            gs = bot.gamestate()
        time.sleep(0.2)
    return gs
