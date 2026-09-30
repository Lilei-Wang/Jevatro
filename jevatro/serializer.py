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


TAG_VALUE = {
    # 高价值：经济/稀有度/翻倍类（wiki 通用战略原则：跳盲只在标签值回票价时划算）
    "DOUBLE": "高价值", "ECONOMIC": "高价值", "Rare": "高价值", "Uncommon": "较高价值",
    "Charm": "较高价值", "Meteor": "较高价值", "Polychrome": "较高价值", "Negative": "较高价值",
    "Standard": "一般", "Common": "一般", "Juggle": "低价值", "Money": "一般",
    "Orbital": "看牌型", "Buffoon": "一般", "Handy": "一般", "Voucher": "较高价值",
    "Coupon": "较高价值", "D6": "看运气", "Familiar": "一般", "Unstable": "低价值",
}


def _tag_value(name: str) -> str:
    for k, v in TAG_VALUE.items():
        if k.lower() in (name or "").lower():
            return v
    return ""


# 公开别名（jev_layer 跳盲题面引用）
def tag_value(name: str) -> str:
    return _tag_value(name)


def _blind_line(gs: dict) -> str:
    parts = []
    boss_preview = ""
    for b in gs.get("blinds", {}).values():
        if not isinstance(b, dict):
            continue
        mark = {"CURRENT": "▶", "SELECT": "○", "UPCOMING": "·", "DEFEATED": "✓", "SKIPPED": "×"}.get(
            b.get("status", ""), " ")
        eff = f", 效果:{b['effect']}" if b.get("effect") else ""
        tag = ""
        if b.get("tag_name") and b.get("type") != "BOSS":
            v = _tag_value(b.get("tag_name", ""))
            tag = f", 跳过奖励:{b['tag_name']}" + (f"({v})" if v else "")
        parts.append(f"{mark}{b['name']}({b.get('type','')}) 需{b.get('score','?')}{eff}{tag}")
        if b.get("type") == "BOSS" and b.get("status") not in ("DEFEATED",) and b.get("effect"):
            boss_preview = f"{b['name']}: {b['effect']}"
    if boss_preview:
        parts.append(f"⚠Boss预告: {boss_preview}（购买时请考虑针对性行卡）")
    return "; ".join(parts)


def deck_stats_line(gs: dict) -> str:
    """R17 卡组修牌视野：全卡组明细（gs.cards.cards）→ 花色/强化/点数分布 + 手牌上限。

    社区共识"卡组修牌是后期天花板"——统一花色/钢化/删废牌的演化目标，
    以及手牌上限（钢K流引擎容量）此前对决策层完全不可见。
    """
    deck = ((gs.get("cards") or {}).get("cards")) or []
    if not deck:
        return ""
    suits = {}
    enh = {}
    ranks = {}
    from scoring import mods as _mods
    for cd in deck:
        s = cd.get("value", {}).get("suit", "?")
        suits[s] = suits.get(s, 0) + 1
        r = cd.get("value", {}).get("rank", "?")
        ranks[r] = ranks.get(r, 0) + 1
        for m in _mods(cd):
            if m in ("STEEL", "GOLD", "WILD", "GLASS", "STONE", "BONUS", "MULT", "LUCKY"):
                enh[m] = enh.get(m, 0) + 1
    SUIT_ZH2 = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
    ENH_ZH2 = {"STEEL": "钢", "GOLD": "金", "WILD": "百搭", "GLASS": "玻璃", "STONE": "石",
               "BONUS": "奖励", "MULT": "倍率", "LUCKY": "幸运"}
    suit_s = " ".join(f"{SUIT_ZH2.get(k,k)}{v}" for k, v in sorted(suits.items()))
    enh_s = " ".join(f"{ENH_ZH2.get(k,k)}{v}" for k, v in sorted(enh.items())) or "无强化"
    top_ranks = sorted(ranks.items(), key=lambda kv: -kv[1])[:2]
    rank_s = " ".join(f"{r}×{n}" for r, n in top_ranks)
    hs = (gs.get("hand") or {}).get("limit")
    hs_s = f"手牌上限{hs}" + ("(偏小,影响引擎容量)" if hs and hs < 8 else "") if hs else ""
    line = f"[卡组] {len(deck)}张: {suit_s} | 强化: {enh_s} | 最多点数: {rank_s}"
    if hs_s:
        line += f" | {hs_s}"
    return line


def serialize(gs: dict, extra_facts: str = "") -> str:
    r = gs.get("round", {})
    lines = []
    lines.append(f"[局] 第{gs.get('ante_num')}轮/{8}周目, 第{gs.get('round_num')}局, "
                 f"金币${gs.get('money')}, 手数{r.get('hands_left')}, 弃牌{r.get('discards_left')}, "
                 f"已得chips {r.get('chips', 0)}")
    # 死因分析结论：深局常囤钱至死——利息上限$25，超出部分不生息
    money = gs.get("money") or 0
    if money >= 26:
        lines.append(f"[经济警示] 金币已超利息上限$25，多出的${money - 25}"
                     f"不产生利息，应尽快转化为战力")
    # M8：利息预告（economy 维度判断的资金事实依据）
    interest = min(money // 5, 5)
    if interest:
        lines.append(f"[利息] 下回合收息 +${interest}(每$5生$1, 上限$5)")
    # 无 X 倍率警示：后程需求指数增长，纯加算小丑会乏力
    # M6 修正：has_x 不能只看已建模效果表——持有未建模的 Xmult（j_ancient/
    # j_steel_joker/j_idol 等）时会输出假警示误导 Jev，改用 curated 全集
    from scoring import XMULT_KEYS
    jok_cards = (gs.get("jokers") or {}).get("cards", [])
    has_x = any(j.get("key", "") in XMULT_KEYS for j in jok_cards)
    if jok_cards and not has_x:
        lines.append("[战力警示] 当前没有任何X倍率小丑, 后续盲注需求指数增长, "
                     "加算类小丑会越来越吃力, X倍率商品优先级应提高")
    # R19 经济转型提示：社区共识 Ante 3-4 起经济价值让位倍率成型
    if (gs.get("ante_num") or 1) >= 4 and money >= 20 and jok_cards and not has_x:
        lines.append("[转型提示] 已到Ante4+且金币充裕——利息循环应让位于战力成型, "
                     "优先把金币转化为X倍率/成长型小丑")
    lines.append(f"[盲注] {_blind_line(gs)}")

    # R17：卡组修牌视野（全卡组明细：花色分布/强化/手牌上限——社区共识的
    # 后期天花板，修牌计划的事实基础）
    deck_line = deck_stats_line(gs)
    if deck_line:
        lines.append(deck_line)

    hands = gs.get("hands", {})
    played = sorted(hands.items(), key=lambda kv: -kv[1].get("played", 0))[:4]
    if played:
        hs = ", ".join(f"{n}Lv{v['level']}({v['chips']}×{v['mult']},已打{v['played']}次)"
                       for n, v in played if v.get("played", 0) > 0)
        if hs:
            lines.append(f"[常用牌型] {hs}")

    jokers = gs.get("jokers", {}).get("cards", [])
    if jokers:
        # M8：附卖价（卖牌腾位决策的回本依据）
        parts = []
        for j in jokers:
            sell = (j.get("cost", {}) or {}).get("sell")
            nm = card_name(j)
            parts.append(f"{nm}(卖${sell})" if sell is not None else nm)
        lines.append(f"[小丑 {len(jokers)}/{gs['jokers'].get('limit', 5)}] " + " | ".join(parts))
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

    # 卡包在独立 packs 区（不在 shop.cards）——不加上 Jev 永远看不见货架上的包
    pack_cards = (gs.get("packs") or {}).get("cards", [])
    if pack_cards:
        entries = [f"{card_name(c)} ${c.get('cost', {}).get('buy', '?')}" for c in pack_cards]
        lines.append(f"[卡包] " + " ; ".join(entries))

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
