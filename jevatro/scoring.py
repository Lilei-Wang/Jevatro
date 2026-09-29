"""算分核：牌型识别 + chips/mult 计算（MVP 精度，支持常见静态小丑）。

设计原则：
- 牌型底分直接用 gamestate.hands 里的等级数据（不重复实现升级公式）；
- modifier/state 在 balatrobot v1.5.2 里是 list（如 ["FOIL"]），用 mods() 兼容 list/dict；
- 小丑只实现"静态可算"的常见效果，未收录的动态小丑按 0 计
  （低估不会导致非法动作，只影响择优精度）。
"""
from __future__ import annotations

RANK_VALUE = {str(n): n for n in range(2, 10)}
RANK_VALUE.update({"T": 10, "J": 11, "Q": 12, "K": 13, "A": 14})
FACE = {"J", "Q", "K"}


def mods(cd: dict) -> set[str]:
    """modifier 归一化：list → set(str)；dict → 非空 key 集合。"""
    m = cd.get("modifier")
    if isinstance(m, list):
        return {x for x in m if isinstance(x, str)}
    if isinstance(m, dict):
        return {k for k, v in m.items() if v}
    return set()


def card_flags(cd: dict) -> set[str]:
    s = cd.get("state")
    if isinstance(s, list):
        return {x for x in s if isinstance(x, str)}
    return set()


# ---------------------------------------------------------------------------
# 牌型识别
# ---------------------------------------------------------------------------

def _rank_counts(cards):
    c: dict[str, int] = {}
    for cd in cards:
        r = cd["value"]["rank"]
        c[r] = c.get(r, 0) + 1
    return c


def rule_flags(jokers: list[dict]) -> dict:
    """规则改变型小丑检测（影响牌型判定本身，非数值加成）。"""
    keys = {j.get("key") for j in jokers}
    return {
        "splash": "j_splash" in keys,            # 打出的牌全部计分
        "four_fingers": "j_four_fingers" in keys,  # 4张即可成同花/顺子
        "shortcut": "j_shortcut" in keys,        # 顺子允许1个间隔
        "smeared": "j_smeared" in keys,          # M3: 红花色一组/黑花色一组
    }


# M3：j_smeared 花色分组映射（H/D 同组，S/C 同组）
_SMEAR_GROUP = {"H": "R", "D": "R", "S": "B", "C": "B"}


def _is_flush(cards, four_fingers: bool = False, smeared: bool = False) -> bool:
    need = 4 if four_fingers else 5
    non_stone = [cd for cd in cards if "STONE" not in mods(cd)]
    if len(cards) < need or len(non_stone) < need:
        return False
    if smeared:
        suits = {_SMEAR_GROUP[cd["value"]["suit"]] for cd in non_stone
                 if cd["value"]["suit"] in _SMEAR_GROUP}
    else:
        suits = {cd["value"]["suit"] for cd in non_stone}
    wilds = any("WILD" in mods(cd) for cd in non_stone)
    return len(suits) == 1 or wilds


def _is_straight(ranks: list[int], shortcut: bool = False, four_fingers: bool = False) -> bool:
    need = 4 if four_fingers else 5
    if len(ranks) < need:
        return False
    s = sorted(set(ranks))
    if len(s) < need:
        return False
    if len(s) == 5 and s == [2, 3, 4, 5, 14]:  # A-5 低顺
        return True
    span = s[-1] - s[0]
    max_span = (need - 1) + (1 if shortcut else 0)
    if span > max_span:
        return False
    if not shortcut:
        return span == need - 1 and len(s) == need
    # shortcut: 相邻差 ∈ {1,2} 且数量足够
    diffs = [b - a for a, b in zip(s, s[1:])]
    return len(s) >= need and all(d in (1, 2) for d in diffs)


def evaluate_hand(played: list[dict], flags: dict | None = None) -> tuple[str, list[int]]:
    """返回 (牌型名, 计分的出牌下标)。played 为 1-5 张已选卡。

    flags: rule_flags() 的结果（four_fingers/shortcut 影响牌型判定）。
    """
    flags = flags or {}
    non_stone = [(i, cd) for i, cd in enumerate(played) if "STONE" not in mods(cd)]
    stone_idx = [i for i, cd in enumerate(played) if "STONE" in mods(cd)]

    ranks = [RANK_VALUE[cd["value"]["rank"]] for _, cd in non_stone]
    counts = _rank_counts([cd for _, cd in non_stone])
    n = len(played)
    cv = sorted(counts.values(), reverse=True)
    flush = _is_flush(played, flags.get("four_fingers", False), flags.get("smeared", False))
    straight = _is_straight(ranks, flags.get("shortcut", False), flags.get("four_fingers", False))

    def idx_of_rank(r: str) -> list[int]:
        return [i for i, cd in non_stone if cd["value"]["rank"] == r]

    def idx_of_count(k: int) -> list[int]:
        return [i for i, cd in non_stone if counts[cd["value"]["rank"]] == k]

    def top_card_idx() -> int:
        best = max(non_stone, key=lambda p: RANK_VALUE[p[1]["value"]["rank"]])
        return best[0]

    if flush and cv and cv[0] == 5:
        name, idx = "Flush Five", list(range(n))
    elif flush and cv[:2] == [3, 2]:
        name, idx = "Flush House", list(range(n))
    elif cv and cv[0] == 5:
        name, idx = "Five of a Kind", list(range(n))
    elif flush and straight:
        name, idx = "Straight Flush", list(range(n))
    elif cv and cv[0] == 4:
        name, idx = "Four of a Kind", idx_of_count(4)
    elif cv[:2] == [3, 2]:
        r3 = [r for r, c in counts.items() if c == 3][0]
        r2 = [r for r, c in counts.items() if c == 2][0]
        name = "Full House"
        idx = idx_of_rank(r3) + idx_of_rank(r2)
    elif flush:
        name, idx = "Flush", list(range(n))
    elif straight:
        name, idx = "Straight", list(range(n))
    elif cv and cv[0] == 3:
        name, idx = "Three of a Kind", idx_of_count(3)
    elif cv[:2] == [2, 2]:
        pairs = sorted([r for r, c in counts.items() if c == 2])
        name = "Two Pair"
        idx = idx_of_rank(pairs[0]) + idx_of_rank(pairs[1])
    elif cv and cv[0] == 2:
        name, idx = "Pair", idx_of_count(2)
    else:
        name, idx = "High Card", [top_card_idx()]
    return name, sorted(set(idx + stone_idx))


# ---------------------------------------------------------------------------
# 小丑效果表（静态子集）
# ---------------------------------------------------------------------------

CONTAINS = {  # "包含某牌型"判断用的映射
    "Pair": ("Pair",),
    "Three of a Kind": ("Three of a Kind", "Full House", "Four of a Kind",
                        "Five of a Kind", "Flush House", "Flush Five"),
    "Two Pair": ("Two Pair", "Full House"),
    "Straight": ("Straight", "Straight Flush"),
    "Flush": ("Flush", "Full House", "Flush House", "Straight Flush", "Flush Five"),
}

JOKER_EFFECTS: dict[str, tuple[str, object]] = {
    "j_joker": ("flat_mult", 4),
    "j_misprint": ("flat_mult", 12),
    "j_popcorn": ("flat_mult", 20),
    "j_gros_michel": ("flat_mult", 15),
    "j_cavendish": ("xmult", 3.0),
    "j_ramen": ("xmult", 2.0),
    "j_ice_cream": ("flat_chips", 100),
    "j_stuntman": ("flat_chips", 250),
    "j_bull": ("flat_chips_per_money", 2),
    "j_banner": ("flat_chips_per_discard", 30),
    "j_blue_joker": ("flat_chips_per_deckcard", 2),
    "j_abstract": ("flat_mult_per_joker", 3),
    "j_jolly": ("contains_mult", ("Pair", 8)),
    "j_zany": ("contains_mult", ("Three of a Kind", 12)),
    "j_mad": ("contains_mult", ("Two Pair", 10)),
    "j_crazy": ("contains_mult", ("Straight", 12)),
    "j_droll": ("contains_mult", ("Flush", 10)),
    "j_half": ("small_hand_mult", 20),
    "j_sly": ("contains_chips", ("Pair", 50)),
    "j_wily": ("contains_chips", ("Three of a Kind", 100)),
    "j_clever": ("contains_chips", ("Two Pair", 80)),
    "j_devious": ("contains_chips", ("Straight", 100)),
    "j_crafty": ("contains_chips", ("Flush", 80)),
    "j_duo": ("contains_xmult", ("Pair", 2.0)),
    "j_trio": ("contains_xmult", ("Three of a Kind", 3.0)),
    "j_family": ("contains_xmult", ("Four of a Kind", 4.0)),
    "j_order": ("contains_xmult", ("Straight", 3.0)),
    "j_tribe": ("contains_xmult", ("Flush", 2.0)),
    "j_stencil": ("xmult_per_empty_joker_slot", 1.0),
    "j_greedy_joker": ("per_card_mult", ("D", 3)),
    "j_lusty_joker": ("per_card_mult", ("H", 3)),
    "j_wrathful_joker": ("per_card_mult", ("S", 3)),
    "j_gluttenous_joker": ("per_card_mult", ("C", 3)),
    "j_onyx_agate": ("per_card_mult", ("C", 7)),
    "j_arrowhead": ("per_card_chips", ("S", 50)),
    "j_fibonacci": ("per_card_rank_mult", ((2, 3, 5, 8, 14), 8)),
    "j_even_steven": ("per_card_parity_mult", ("even", 4)),
    "j_odd_todd": ("per_card_parity_chips", ("odd", 31)),
    "j_smiley": ("per_card_face_mult", 5),
    "j_triboulet": ("per_card_rank_xmult", ((12, 13), 2.0)),
    "j_scholar": ("per_card_ace", (20, 4)),
    "j_walkie_talkie": ("per_card_rank_hybrid", ((10, 4), 10, 4)),
    "j_flower_pot": ("all_suits_xmult", 3.0),
    "j_mystic_summit": ("no_discard_mult", 15),
    "j_acrobat": ("xmult", 3.0),
    # ---- 动态/成长型小丑的中局近似值（低于真值优于 0 低估，只影响择优排序）----
    "j_green_joker": ("flat_mult", 6),
    "j_ride_the_bus": ("flat_mult", 8),
    "j_supernova": ("flat_mult", 3),
    "j_runner": ("flat_chips", 40),
    "j_trousers": ("contains_mult", ("Two Pair", 8)),
    "j_constellation": ("xmult", 1.3),
    "j_hologram": ("xmult", 1.5),
    "j_obelisk": ("xmult", 2.0),
    "j_vampire": ("xmult", 1.2),
    "j_campfire": ("xmult", 1.5),
    "j_lucky_cat": ("xmult", 1.3),
    "j_flash": ("flat_mult", 8),
    "j_photograph": ("xmult", 1.8),
    "j_loyalty_card": ("xmult", 1.6),
    "j_hit_the_road": ("xmult", 1.3),
    "j_glass": ("xmult", 1.5),
    "j_erosion": ("flat_mult", 8),
    "j_castle": ("flat_chips", 25),
    "j_bloodstone": ("per_card_mult", ("H", 1)),
    # M5：Baron 真实效果是每张在手 K ×1.5（旧固定 xmult 2.0 高估无 K 场景）
    "j_baron": ("xmult_per_held_king", 1.5),
    "j_shoot_the_moon": ("flat_mult", 6),
    "j_blackboard": ("xmult", 1.5),
    "j_card_sharp": ("xmult", 1.5),
    "j_sock_and_buskin": ("flat_mult", 8),
    "j_hack": ("flat_mult", 8),
    "j_selzer": ("flat_mult", 6),
    "j_burglar": ("flat_mult", 8),
    "j_troubadour": ("flat_mult", 6),
    "j_juggler": ("flat_mult", 4),
    "j_drunkard": ("flat_mult", 3),
    "j_merry_andy": ("flat_mult", 5),
    "j_yorick": ("xmult", 1.5),
    "j_caino": ("xmult", 1.3),
    # ---- M6 补充（效果取自 card_desc/balatrobot 文档）----
    "j_scary_face": ("per_card_face_chips", 30),      # 人脸计分卡 +30 chips
    "j_seeing_double": ("seeing_double_xmult", 2.0),  # 计分有梅花+其他花色 → X2
    "j_swashbuckler": ("mult_per_other_joker_sell", 1),  # 其他小丑卖价加到 Mult
    # 成长型的中局近似（同上节口径）
    "j_square": ("flat_chips", 40),                   # 4张手牌每局+4 chips
    "j_wee": ("flat_chips", 40),                      # 每张2计分+8 chips
    "j_fortune_teller": ("flat_mult", 6),             # 每张已用塔罗+1 mult
    "j_red_card": ("flat_mult", 9),                   # 每跳过一包+3 mult
    "j_hanging_chad": ("retrigger_first", 2),         # 首张计分卡重触发2次
    "j_raised_fist": ("lowest_held_mult", 2),         # 在手最低点数×2加 Mult
    "j_mime": ("mime", 1),                            # 在手卡效果重触发（钢牌×2）
    # 无法可靠建模（需牌组构成/每轮变化目标/rarity，gamestate 未提供，按 0 计）：
    # j_stone/j_steel_joker/j_drivers_license（依赖全牌组构成）、
    # j_idol/j_ancient（目标每轮变化）、j_baseball（小丑 rarity 不在 gamestate）、
    # j_dusk（仅最后一手）、Blueprint/Brainstorm（邻位复制）
}

# X 倍率小丑全集（含未建模卡）——serializer 的"无X倍率警示"用，
# 避免持有未建模 Xmult 时误报"没有任何X倍率小丑"
_XMULT_KINDS = {"xmult", "contains_xmult", "xmult_per_held_king", "seeing_double_xmult"}
XMULT_KEYS = {k for k, (kind, _) in JOKER_EFFECTS.items()
              if kind in _XMULT_KINDS or kind == "per_card_rank_xmult"} | {
    # 未建模但确为 X 倍率的卡（据 card_desc）
    "j_ancient", "j_steel_joker", "j_idol", "j_baseball", "j_drivers_license",
    "j_madness", "j_throwback", "j_to_the_moon", "j_bloodstone",
}


def _card_chips(cd: dict) -> int:
    if "STONE" in mods(cd):
        base = 50
    else:
        r = cd["value"]["rank"]
        v = RANK_VALUE[r]
        base = 11 if r == "A" else (10 if v >= 10 else v)
    if "FOIL" in mods(cd):
        base += 50
    return base


def _card_mult(cd: dict) -> tuple[float, float]:
    """返回 (加算mult, 乘算mult)。"""
    add, mult = 0.0, 1.0
    m = mods(cd)
    if "MULT" in m:
        add += 4
    elif "GLASS" in m:
        mult *= 2.0
    if "HOLO" in m:
        add += 10
    elif "POLYCHROME" in m:
        mult *= 1.5
    return add, mult


def _enh_chips(cd: dict) -> int:
    return 30 if "BONUS" in mods(cd) else 0


def score_play(
    played: list[dict],
    scoring_idx: list[int],
    hand_name: str,
    hand_levels: dict,
    jokers: list[dict],
    ctx: dict,
    debuff_idx: set[int] | None = None,
) -> dict:
    """debuff_idx: 被弱化的出牌下标（0 筹码、无卡牌效果，但计入牌型）。

    M4：mult 改为按小丑从左到右顺序即时结算（+先加、X再乘当前值），
    旧版"全部加完再乘"在 +mult 位于 Xmult 右侧时系统性高估。
    M5：新增在手效果（钢牌×1.5/Baron每王/最低点数/mime 双触发）。
    """
    debuff_idx = debuff_idx or set()
    base = hand_levels.get(hand_name) or {"chips": 5, "mult": 1}
    chips = float(base["chips"])
    mult = float(base["mult"])

    if ctx.get("splash"):  # j_splash: 打出的牌全部计分
        scoring_idx = [i for i, _ in enumerate(played) if i not in debuff_idx]
    # 弱化牌（花色 Boss）：计牌型但 0 筹码 0 效果
    eff_idx = [i for i in scoring_idx if i not in debuff_idx]
    scoring = [played[i] for i in eff_idx]

    # hanging_chad：首张计分卡重触发（其贡献再计 arg 次）
    retrigger_first = 0
    for jk in jokers:
        eff = JOKER_EFFECTS.get(jk.get("key", ""))
        if eff and eff[0] == "retrigger_first":
            retrigger_first = eff[1]
    first_contrib = None
    for pos, cd in enumerate(scoring):
        c_chips = _card_chips(cd) + _enh_chips(cd)
        a, m = _card_mult(cd)
        chips += c_chips
        mult += a
        mult *= m
        if pos == 0:
            first_contrib = (c_chips, a, m)
    if first_contrib and retrigger_first:
        chips += first_contrib[0] * retrigger_first
        mult += first_contrib[1] * retrigger_first
        mult *= first_contrib[2] ** retrigger_first

    empty_slots = max(0, ctx.get("joker_slots", 5) - len(jokers))
    has_mime = any(j.get("key") == "j_mime" for j in jokers)
    for jk in jokers:
        eff = JOKER_EFFECTS.get(jk.get("key", ""))
        jm = mods(jk)
        if "FOIL" in jm:
            chips += 50
        elif "HOLO" in jm:
            mult += 10
        elif "POLYCHROME" in jm:
            mult *= 1.5
        if not eff:
            continue
        kind, arg = eff
        if kind == "flat_mult":
            mult += arg
        elif kind == "flat_chips":
            chips += arg
        elif kind == "xmult":
            mult *= arg
        elif kind == "flat_chips_per_money":
            chips += arg * ctx.get("money", 0)
        elif kind == "flat_chips_per_discard":
            chips += arg * ctx.get("discards_left", 0)
        elif kind == "flat_chips_per_deckcard":
            chips += arg * ctx.get("deck_remaining", 40)
        elif kind == "flat_mult_per_joker":
            mult += arg * len(jokers)
        elif kind == "contains_mult":
            t, v = arg
            if hand_name in CONTAINS.get(t, ()):
                mult += v
        elif kind == "contains_chips":
            t, v = arg
            if hand_name in CONTAINS.get(t, ()):
                chips += v
        elif kind == "contains_xmult":
            t, v = arg
            if hand_name in CONTAINS.get(t, ()):
                mult *= v
        elif kind == "small_hand_mult":
            if len(played) <= 3:
                mult += arg
        elif kind == "per_card_mult":
            suit, v = arg
            mult += v * sum(1 for c in scoring if c["value"]["suit"] == suit
                            or "WILD" in mods(c))
        elif kind == "per_card_chips":
            suit, v = arg
            chips += v * sum(1 for c in scoring if c["value"]["suit"] == suit
                             or "WILD" in mods(c))
        elif kind == "per_card_rank_mult":
            ranks, v = arg
            mult += v * sum(1 for c in scoring if RANK_VALUE[c["value"]["rank"]] in ranks)
        elif kind == "per_card_rank_xmult":
            ranks, v = arg
            for c in scoring:
                if RANK_VALUE[c["value"]["rank"]] in ranks:
                    mult *= v
        elif kind == "per_card_parity_mult":
            par, v = arg
            mult += v * sum(1 for c in scoring
                            if RANK_VALUE[c["value"]["rank"]] != 14
                            and RANK_VALUE[c["value"]["rank"]] % 2 == (0 if par == "even" else 1))
        elif kind == "per_card_parity_chips":
            par, v = arg
            chips += v * sum(1 for c in scoring
                             if RANK_VALUE[c["value"]["rank"]] != 14
                             and RANK_VALUE[c["value"]["rank"]] % 2 == (0 if par == "even" else 1))
        elif kind == "per_card_face_mult":
            mult += arg * sum(1 for c in scoring if c["value"]["rank"] in FACE)
        elif kind == "per_card_face_chips":       # M6
            chips += arg * sum(1 for c in scoring if c["value"]["rank"] in FACE)
        elif kind == "per_card_ace":
            ch, mu = arg
            n = sum(1 for c in scoring if c["value"]["rank"] == "A")
            chips += ch * n
            mult += mu * n
        elif kind == "per_card_rank_hybrid":
            ranks, ch, mu = arg
            n = sum(1 for c in scoring if RANK_VALUE[c["value"]["rank"]] in ranks)
            chips += ch * n
            mult += mu * n
        elif kind == "all_suits_xmult":
            suits = {c["value"]["suit"] for c in scoring}
            if suits >= {"H", "D", "C", "S"}:
                mult *= arg
        elif kind == "no_discard_mult":
            if ctx.get("discards_left", 0) == 0:
                mult += arg
        elif kind == "xmult_per_empty_joker_slot":
            mult *= max(1.0, arg * empty_slots)
        elif kind == "seeing_double_xmult":       # M6：计分含梅花且有其他花色
            suits = {c["value"]["suit"] for c in scoring}
            if "C" in suits and len(suits) >= 2:
                mult *= arg
        elif kind == "mult_per_other_joker_sell":  # M6：其他小丑卖价之和
            mult += sum((j.get("cost", {}) or {}).get("sell", 1)
                        for j in jokers if j is not jk)
        elif kind == "lowest_held_mult":          # M5：在手最低点数×2
            r = ctx.get("lowest_held_rank")
            if r:
                mult += arg * RANK_VALUE.get(r, 0)
        elif kind == "xmult_per_held_king":       # M5：Baron 每张在手 K
            mult *= arg ** ctx.get("held_kings", 0)

    # M5：在手钢牌 ×1.5（mime 在手时双触发）
    held_steel = ctx.get("held_steel", 0)
    if held_steel:
        mult *= 1.5 ** (held_steel * (2 if has_mime else 1))

    return {"hand": hand_name, "chips": chips, "mult": mult, "total": chips * mult}
