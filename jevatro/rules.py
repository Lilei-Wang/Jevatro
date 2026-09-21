"""Boss 盲规则引擎：把 Boss 约束前置于求解器，主动只生成合法出牌。

实测教训（JEVATRO1 ante1 r3, The Psychic）：非 5 张出牌 API 不报错，
但 0 分白烧一手 —— 必须在枚举层过滤。
"""
from __future__ import annotations

# 花色 Boss：该花色的牌被"弱化"（debuff）：0 筹码、无任何卡牌效果，但仍计入牌型判定
SUIT_BOSSES = {"The Club": "C", "The Goad": "S", "The Head": "H", "The Window": "D"}


def current_blind(gs: dict) -> dict | None:
    for b in gs.get("blinds", {}).values():
        if isinstance(b, dict) and b.get("status") in ("CURRENT", "SELECT"):
            return b
    return None


def boss_rules(gs: dict) -> dict:
    """返回当前盲注（Boss 或普通）对出牌/算分的约束。"""
    blind = current_blind(gs)
    name = blind.get("name", "") if blind else ""
    return {
        "blind_name": name,
        "is_boss": (blind or {}).get("type") == "BOSS",
        "exact_play": 5 if name == "The Psychic" else None,      # 必须出 5 张
        "debuff_suit": SUIT_BOSSES.get(name),                    # 该花色全弱化
        "no_repeat_type": name == "The Eye",                     # 本轮不可重复牌型
        "only_one_type": name == "The Mouth",                    # 本轮只能打一种牌型
        "the_arm": name == "The Arm",                            # 打出的牌型降 1 级后结算
        "flint": name == "The Flint",                            # 底分筹码与倍率减半
        "ox": name == "The Ox",                                  # 打最多使用牌型会清空金币
    }


def is_debuffed(cd: dict, rules: dict) -> bool:
    """卡牌弱化判定：Boss 花色弱化，或游戏状态标记弱化。"""
    if rules.get("debuff_suit") and cd.get("value", {}).get("suit") == rules["debuff_suit"]:
        return True
    s = cd.get("state")
    flags = s if isinstance(s, list) else ([k for k, v in (s or {}).items() if v] if isinstance(s, dict) else [])
    return any("debuff" in str(x).lower() for x in flags)


def legal_hand_types(gs: dict, rules: dict) -> tuple[set[str] | None, set[str]]:
    """返回 (仅允许的牌型集合|None, 禁用牌型集合)。

    The Eye: 已打过的牌型禁用；The Mouth: 只允许本轮第一个打出的牌型。
    """
    banned: set[str] = set()
    only: set[str] | None = None
    if not (rules.get("no_repeat_type") or rules.get("only_one_type")):
        return None, banned
    played_types = {name for name, h in gs.get("hands", {}).items()
                    if h.get("played_this_round", 0) > 0}
    if rules.get("no_repeat_type"):
        banned |= played_types
    if rules.get("only_one_type") and played_types:
        only = played_types  # 只剩这一个允许
    return only, banned


# 牌型底分与每级增量（用于 The Arm 降级估算）
BASE_AND_INC: dict[str, tuple[int, int, int, int]] = {
    # name: (base_chips, base_mult, inc_chips, inc_mult)
    "High Card": (5, 1, 10, 1),
    "Pair": (10, 2, 15, 1),
    "Two Pair": (20, 2, 20, 1),
    "Three of a Kind": (30, 3, 20, 2),
    "Straight": (30, 4, 30, 3),
    "Flush": (35, 4, 15, 2),
    "Full House": (40, 4, 25, 2),
    "Four of a Kind": (60, 7, 30, 3),
    "Straight Flush": (100, 8, 40, 4),
    "Five of a Kind": (120, 12, 35, 3),
    "Flush House": (140, 14, 40, 4),
    "Flush Five": (160, 16, 50, 3),
}


def effective_hand_levels(gs: dict, rules: dict) -> dict:
    """按 The Arm（打出牌型先降 1 级）调整后的牌型底分表。"""
    hands = gs.get("hands", {})
    out = {}
    for name, h in hands.items():
        chips, mult = h.get("chips", 0), h.get("mult", 0)
        level = h.get("level", 1)
        if rules.get("the_arm") and name in BASE_AND_INC and level > 1:
            bc, bm, ic, im = BASE_AND_INC[name]
            eff_level = max(1, level - 1)
            chips = bc + (eff_level - 1) * ic
            mult = bm + (eff_level - 1) * im
        if rules.get("flint"):
            chips = chips // 2
            mult = mult // 2
        out[name] = {"chips": chips, "mult": mult, "level": level}
    return out


def most_played_hand(gs: dict) -> str | None:
    hands = gs.get("hands", {})
    played = [(n, h.get("played", 0)) for n, h in hands.items() if h.get("played", 0) > 0]
    return max(played, key=lambda x: x[1])[0] if played else None
