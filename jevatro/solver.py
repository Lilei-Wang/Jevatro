"""出牌求解器：枚举全部 ≤5 张出牌组合，返回最优。"""
from __future__ import annotations

from itertools import combinations

from scoring import evaluate_hand, score_play


def all_plays(hand_cards: list[dict]) -> list[tuple[tuple[int, ...], str]]:
    out = []
    n = len(hand_cards)
    for k in range(1, 6):
        for combo in combinations(range(n), k):
            played = [hand_cards[i] for i in combo]
            name, _ = evaluate_hand(played)
            out.append((combo, name))
    return out


def best_play(gamestate: dict) -> dict:
    """返回 {indices, hand, chips, mult, total, need, can_clear}。"""
    hand_cards = gamestate["hand"]["cards"]
    jokers = gamestate.get("jokers", {}).get("cards", [])
    hand_levels = gamestate.get("hands", {})
    cards_area = gamestate.get("cards") or {}
    ctx = {
        "money": gamestate.get("money", 0),
        "discards_left": gamestate.get("round", {}).get("discards_left", 0),
        "deck_remaining": cards_area.get("count", 40) if isinstance(cards_area, dict) else 40,
        "joker_slots": gamestate.get("jokers", {}).get("limit", 5),
    }

    best = None
    for combo, name in all_plays(hand_cards):
        played = [hand_cards[i] for i in combo]
        _, scoring_idx = evaluate_hand(played)
        s = score_play(played, scoring_idx, name, hand_levels, jokers, ctx)
        if best is None or s["total"] > best["total"]:
            best = {"indices": list(combo), **s}

    hands_left = gamestate.get("round", {}).get("hands_left", 1)
    current_chips = gamestate.get("round", {}).get("chips", 0)
    blind_score = _current_blind_score(gamestate)
    best["need"] = blind_score
    best["can_clear"] = (current_chips + best["total"] * hands_left) >= blind_score
    return best


def _current_blind_score(gs: dict) -> int:
    for b in gs.get("blinds", {}).values():
        if isinstance(b, dict) and b.get("status") == "CURRENT":
            return b.get("score", 300)
    blinds = list(gs.get("blinds", {}).values())
    return blinds[0].get("score", 300) if blinds else 300
