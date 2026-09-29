"""出牌求解器：枚举全部 ≤5 张组合，按 Boss 规则过滤后取最优（Tier 0）。"""
from __future__ import annotations

from itertools import combinations

from rules import (boss_rules, effective_hand_levels, is_debuffed,
                   legal_hand_types, most_played_hand)
from scoring import RANK_VALUE, evaluate_hand, mods, rule_flags, score_play


def all_plays(hand_cards: list[dict], rules: dict,
              only_types: set | None, banned_types: set,
              flags: dict | None = None) -> list[tuple[tuple[int, ...], str]]:
    out = []
    n = len(hand_cards)
    k_fixed = rules.get("exact_play")
    ks = [k_fixed] if k_fixed else range(1, 6)
    for k in ks:
        if k > n:
            continue
        for combo in combinations(range(n), k):
            played = [hand_cards[i] for i in combo]
            name, _ = evaluate_hand(played, flags)
            if only_types is not None and name not in only_types:
                continue
            if name in banned_types:
                continue
            out.append((combo, name))
    return out


def best_play(gamestate: dict) -> dict:
    """返回 {indices, hand, chips, mult, total, need, can_clear, rules}。"""
    gs = gamestate
    hand_cards = gs["hand"]["cards"]
    jokers = gs.get("jokers", {}).get("cards", [])
    rules = boss_rules(gs)
    hand_levels = effective_hand_levels(gs, rules)
    only_types, banned_types = legal_hand_types(gs, rules)
    flags = rule_flags(jokers)
    cards_area = gs.get("cards") or {}
    # M5：在手效果统计（钢牌/王数/最低点数——供 score_play 的在手加成）
    hand_all = gs.get("hand", {}).get("cards", [])
    held_ranks = [c["value"]["rank"] for c in hand_all]
    ctx = {
        "money": gs.get("money", 0),
        "discards_left": gs.get("round", {}).get("discards_left", 0),
        "deck_remaining": cards_area.get("count", 40) if isinstance(cards_area, dict) else 40,
        "joker_slots": gs.get("jokers", {}).get("limit", 5),
        "held_steel": sum(1 for c in hand_all if "STEEL" in mods(c)),
        "held_kings": sum(1 for r in held_ranks if r == "K"),
        "lowest_held_rank": min(held_ranks, key=lambda r: RANK_VALUE.get(r, 0)) if held_ranks else None,
        **flags,
    }
    debuff_idx_global = {i for i, cd in enumerate(hand_cards) if is_debuffed(cd, rules)}

    plays = all_plays(hand_cards, rules, only_types, banned_types, flags)
    if not plays and rules.get("exact_play"):
        # 兜底：极端情况下（如 The Mouth 冲突 + Psychic 叠加）放弃牌型过滤保张数
        plays = [(c, evaluate_hand([hand_cards[i] for i in c], flags)[0])
                 for c in combinations(range(len(hand_cards)), rules["exact_play"])
                 if len(c) <= len(hand_cards)]

    ranked = []
    for combo, name in plays:
        played = [hand_cards[i] for i in combo]
        _, scoring_idx = evaluate_hand(played, flags)
        # 弱化牌下标转换：手牌下标 → 出牌组合内下标（此前两套空间混用，
        # 弱化牌从未真正清零 → 花色Boss下照常计分、不避讳弱化牌）
        debuffed = {pi for pi, hi in enumerate(combo) if hi in debuff_idx_global}
        s = score_play(played, scoring_idx, name, hand_levels, jokers, ctx,
                       debuff_idx=debuffed)
        ranked.append(({"indices": list(combo), **s}))

    ranked.sort(key=lambda x: -x["total"])
    best = ranked[0] if ranked else None

    # 无合法组合（极端约束叠加/换牌动画间隙）：退化为前 min(5) 张
    if best is None:
        n = min(5, len(hand_cards))
        if n == 0:
            return {"indices": [], "hand": "-", "chips": 0, "mult": 0, "total": 0,
                    "need": _current_blind_score(gs), "can_clear": False,
                    "rules": {k: v for k, v in rules.items() if v not in (None, False)}}
        combo = list(range(n))
        played = [hand_cards[i] for i in combo]
        name, scoring_idx = evaluate_hand(played)
        best = {"indices": combo,
                **score_play(played, scoring_idx, name, hand_levels, jokers, ctx)}

    # The Ox：打"最多使用牌型"会清空金币 → 有近似替代时避开
    if best and rules.get("ox"):
        victim = most_played_hand(gs)
        if victim and best["hand"] == victim and gs.get("money", 0) >= 15:
            alt = next((r for r in ranked if r["hand"] != victim
                        and r["total"] >= best["total"] * 0.9), None)
            if alt:
                best = {**alt, "ox_avoided": victim}

    hands_left = gs.get("round", {}).get("hands_left", 1)
    current_chips = gs.get("round", {}).get("chips", 0)
    blind_score = _current_blind_score(gs)
    best["need"] = blind_score
    best["can_clear"] = (current_chips + best["total"] * hands_left) >= blind_score
    best["rules"] = {k: v for k, v in rules.items() if v not in (None, False)}
    return best


def best_discard(gs: dict) -> list[int]:
    """弃牌策略：保住最优组合"方向"，弃掉边缘牌（最多5张）。

    持有价值牌优先保留（wiki 魔典原则）：钢牌在手即 ×1.5 倍率（永不弃）、
    金牌每回合 +$3（方向牌不足时才可让位）。
    """
    hand_cards = gs["hand"]["cards"]
    discards_left = gs.get("round", {}).get("discards_left", 0)
    if discards_left <= 0 or len(hand_cards) <= 5:
        return []

    def held_value(cd) -> str | None:
        m = mods(cd)
        if "STEEL" in m:
            return "steel"
        if "GOLD" in m:
            return "gold"
        return None

    bp = best_play(gs)
    keep = set(bp["indices"])
    combo_cards = [hand_cards[i] for i in bp["indices"]]

    # 方向保持：组合里出现≥3张同花色 → 保留同花色牌；对子/三条 → 保留同点数
    suits = [c["value"]["suit"] for c in combo_cards]
    ranks = [c["value"]["rank"] for c in combo_cards]
    keep_suit = max(set(suits), key=suits.count) if suits and suits.count(max(set(suits), key=suits.count)) >= 3 else None
    keep_rank = max(set(ranks), key=ranks.count) if ranks and ranks.count(max(set(ranks), key=ranks.count)) >= 2 else None

    for i, cd in enumerate(hand_cards):
        if i in keep:
            continue
        hv = held_value(cd)
        if hv == "steel":
            keep.add(i)          # 钢牌：在手 ×1.5 倍率，永不弃
            continue
        if hv == "gold":
            keep.add(i)          # 金牌：每回合 +$3，优先保留
            continue
        if keep_suit and cd["value"]["suit"] == keep_suit:
            keep.add(i)
        elif keep_rank and cd["value"]["rank"] == keep_rank:
            keep.add(i)

    # 全保住凑不够弃牌数时，金牌可让位（钢牌绝不弃）
    while len([i for i in range(len(hand_cards)) if i not in keep]) < 1:
        golds = [i for i in keep if i not in bp["indices"]
                 and held_value(hand_cards[i]) == "gold"]
        if not golds:
            break
        keep.discard(golds[0])

    discard = [i for i in range(len(hand_cards)) if i not in keep][:5]
    return discard


def _current_blind_score(gs: dict) -> int:
    for b in gs.get("blinds", {}).values():
        if isinstance(b, dict) and b.get("status") in ("CURRENT", "SELECT"):
            return b.get("score", 300)
    blinds = list(gs.get("blinds", {}).values())
    return blinds[0].get("score", 300) if blinds else 300
