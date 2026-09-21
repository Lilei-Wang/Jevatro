"""gamestate → Jev state 紧凑文本（中文，含卡牌释义）。"""
from __future__ import annotations

from card_desc import CARD_DESC
from solver import best_play, _current_blind_score

SUIT_ZH = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}


def card_name(cd: dict) -> str:
    """key + 本地化名 + 释义（如 j_joker(Joker): +4 Mult）。"""
    key = cd.get("key", "?")
    label = cd.get("label", "")
    desc = CARD_DESC.get(key, "")
    mod = _mods_brief(cd)
    name = f"{key}({label})" if label and label != "Base Card" else key
    if desc:
        name += f": {desc}"
    if mod:
        name += f" [{mod}]"
    return name


_MOD_NOISE = {"enhancement", "edition", "seal", "eternal", "perishable", "rental",
              "None", "none", "null"}


def _mods_brief(cd: dict) -> str:
    m = cd.get("modifier")
    items = m if isinstance(m, list) else [k for k, v in (m or {}).items() if v]
    items = [str(x) for x in items if str(x) not in _MOD_NOISE]
    return "/".join(items)


def playing_card(cd: dict) -> str:
    v = cd["value"]
    mod = _mods_brief(cd)
    s = f"{SUIT_ZH.get(v['suit'], v['suit'])}{v['rank']}"
    return f"{s}({mod})" if mod else s


def _blind_line(gs: dict) -> str:
    parts = []
    for b in gs.get("blinds", {}).values():
        if not isinstance(b, dict):
            continue
        mark = {"CURRENT": "▶", "SELECT": "○", "UPCOMING": "·", "DEFEATED": "✓", "SKIPPED": "×"}.get(
            b.get("status", ""), " ")
        eff = f", 效果:{b['effect']}" if b.get("effect") else ""
        tag = f", 跳过奖励:{b['tag_name']}" if b.get("tag_name") and b.get("type") != "BOSS" else ""
        parts.append(f"{mark}{b['name']}({b.get('type','')}) 需{b.get('score','?')}{eff}{tag}")
    return "; ".join(parts)


def serialize(gs: dict, extra_facts: str = "") -> str:
    r = gs.get("round", {})
    lines = []
    lines.append(f"[局] 第{gs.get('ante_num')}轮/{8}周目, 第{gs.get('round_num')}局, "
                 f"金币${gs.get('money')}, 手数{r.get('hands_left')}, 弃牌{r.get('discards_left')}, "
                 f"已得chips {r.get('chips', 0)}")
    lines.append(f"[盲注] {_blind_line(gs)}")

    hands = gs.get("hands", {})
    played = sorted(hands.items(), key=lambda kv: -kv[1].get("played", 0))[:4]
    if played:
        hs = ", ".join(f"{n}Lv{v['level']}({v['chips']}×{v['mult']},已打{v['played']}次)"
                       for n, v in played if v.get("played", 0) > 0)
        if hs:
            lines.append(f"[常用牌型] {hs}")

    jokers = gs.get("jokers", {}).get("cards", [])
    if jokers:
        lines.append(f"[小丑 {len(jokers)}/{gs['jokers'].get('limit', 5)}] " +
                     " | ".join(card_name(j) for j in jokers))
    else:
        lines.append("[小丑] 无")

    consumables = gs.get("consumables", {}).get("cards", [])
    if consumables:
        lines.append(f"[消耗牌] " + " | ".join(card_name(c) for c in consumables))

    hand_cards = gs.get("hand", {}).get("cards", [])
    if hand_cards:
        lines.append(f"[手牌] " + " ".join(playing_card(c) for c in hand_cards))

    shop_cards = gs.get("shop", {}).get("cards", [])
    if shop_cards:
        entries = []
        for c in shop_cards:
            entries.append(f"{card_name(c)} ${c.get('cost', {}).get('buy', '?')}")
        lines.append(f"[商店] " + " ; ".join(entries))

    pack_cards = gs.get("pack", {}).get("cards", [])
    if pack_cards:
        lines.append(f"[开包可选] " + " | ".join(card_name(c) for c in pack_cards))

    voucher = gs.get("vouchers", {}).get("cards", [])
    if voucher:
        lines.append(f"[兑换券] " + " | ".join(card_name(v) for v in voucher))

    if extra_facts:
        lines.append(f"[求解器事实] {extra_facts}")
    return "\n".join(lines)


def solver_facts(gs: dict) -> dict:
    """求解器可精确算出的事实，供 state 附加与决策参考。"""
    hand_cards = gs.get("hand", {}).get("cards", [])
    out: dict = {"blind_score": _current_blind_score(gs)}
    if gs.get("state") == "SELECTING_HAND" and hand_cards:
        bp = best_play(gs)
        out["best_play"] = bp["hand"]
        out["best_total"] = bp["total"]
        out["can_clear"] = bp["can_clear"]
    facts = out.copy()
    if "best_total" in facts:
        extra = (f"最优出牌: {facts['best_play']} = {facts['best_total']:.0f}分; "
                 f"盲注需求{facts['blind_score']}; "
                 f"{'剩余手数预计可过' if facts.get('can_clear') else '按最优打法剩余手数不足以过关'}")
    else:
        extra = f"盲注需求{facts['blind_score']}"
    return {**facts, "text": extra}
