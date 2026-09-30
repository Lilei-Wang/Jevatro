"""Jev 决策层（Tier 1）：商店 Composite Scoring + 盲注 Noul + 方向识别 fan-out。

所有题目混装进一次 system_one 调用（并行隔离执行），置信度不足走保守默认。
Jev API 失败时回退到 naive 策略，保证 bot 永远能继续打。
"""
from __future__ import annotations

import os
import time

from serializer import card_name, serialize, solver_facts, tag_value
from solver import best_play
from use_policy import buy_ok

import pricing

# ---------------------------------------------------------------------------
# 环境
# ---------------------------------------------------------------------------

def load_env() -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


def _init_client():
    from typesafe_sdk import TypeSafeClient
    return TypeSafeClient(timeout=30.0)


# ---------------------------------------------------------------------------
# 权重表：archetype → 四维权重
# ---------------------------------------------------------------------------

WEIGHTS: dict[str, dict[str, float]] = {
    "default":  {"synergy": 0.40, "scaling": 0.25, "economy": 0.15, "immediate": 0.20},
    "flush":    {"synergy": 0.50, "scaling": 0.25, "economy": 0.10, "immediate": 0.15},
    "pair":     {"synergy": 0.45, "scaling": 0.25, "economy": 0.12, "immediate": 0.18},
    "highcard": {"synergy": 0.50, "scaling": 0.30, "economy": 0.08, "immediate": 0.12},
    "straight": {"synergy": 0.45, "scaling": 0.25, "economy": 0.12, "immediate": 0.18},
    # L1：balanced 选项此前回落 default 再与 default 混合，BLEND 数学空转
    "balanced": {"synergy": 0.40, "scaling": 0.25, "economy": 0.15, "immediate": 0.20},
}

# 方向识别：单题 Choice（旧版 5 连 Noul 有 28% 未达阈值，区分度不足）
ARCH_CHOICE = {
    "pair": "对子/三条/满堂方向: 以重复点数为核心",
    "flush": "同花方向: 以花色一致为核心",
    "straight": "顺子方向: 以连续点数为核心",
    "highcard": "高牌+固定加成方向: 少张出牌配合独立数值小丑",
    "balanced": "方向未定/均衡: 缺乏明确核心, 需要通用成长",
}

DIMS = {
    "synergy":  "该商品与现有小丑/牌型等级的协同程度",
    "scaling":  "该商品的长期成长性(以本局剩余周目视角)",
    # H2：旧措辞"对金钱循环的贡献"让战斗小丑恒 0-1 分（0.15 权重纯扣分），
    # 且售价从不进任何维度——改为承载"性价比"，价格终于有维度归口
    "economy":  "该商品考虑其标价后的资金性价比(与对战力/经济的贡献相比是否值这个价)",
    "immediate": "该商品对接下来1-2个盲注得分能力的提升程度",
}
RUBRIC = {
    "synergy":  ["0 与现有构筑零交互甚至冲突", "1 略相关但方向不符", "2 中性填充",
                 "3 明确加强现有方向", "4 核心拼图,改变战力曲线"],
    "scaling":  ["0 无成长", "1 一次性收益", "2 轻微成长", "3 每轮稳定成长", "4 复利式成长"],
    "economy":  ["0 明显溢价完全不值", "1 偏贵", "2 价格与价值相称", "3 物有所值",
                 "4 白捡级性价比"],
    "immediate": ["0 对得分完全无助", "1 略有帮助", "2 有一定帮助", "3 显著提升近期得分",
                  "4 立刻改变能否过关"],
}

BUY_VALUE_TAU = 0.40    # 综合价值阈值（置信度仅记录不门控：实测 conf=0.0 是"无信号"非"不可靠"）
BLEND_DEFAULT = 0.5     # 方向权重与 default 各占一半（防止 econ 方向过度稀释战力权重）

# L2：星球确定性升级加成/减分（答后加权，替代旧的进候选前预过滤——
# 旧过滤在 Jev 回答之前就用代码侧方向估算把星球挡掉，ante 1-2 全灭）
PLANET_MATCH_BONUS = 0.10
PLANET_MISMATCH_PENALTY = 0.15

# 可买的卡包：小丑包(加槽)/标准牌包(进牌组)/天体包(星球即用)/
# 塔罗包/幻灵包（开包选卡已由 pack_pick 支持，解禁）
BUYABLE_PACK_PREFIXES = ("p_buffoon", "p_standard", "p_celestial", "p_tarot", "p_spectral")

# 星球卡 → 牌型（购买守卫：只买升级主力/常用牌型的星球，避免浪费）
PLANET_HAND = {
    "c_mercury": "Pair", "c_venus": "Three of a Kind", "c_earth": "Full House",
    "c_mars": "Four of a Kind", "c_jupiter": "Flush", "c_saturn": "Straight",
    "c_uranus": "Two Pair", "c_neptune": "Straight Flush", "c_pluto": "High Card",
    "c_planet_x": "Five of a Kind", "c_ceres": "Flush House", "c_eris": "Flush Five",
}
# 方向关键词 → 对应牌型（arch 匹配时放行）
ARCH_HANDS = {
    "pair": {"Pair", "Two Pair", "Three of a Kind", "Full House"},
    "flush": {"Flush", "Full House", "Flush House"},
    "straight": {"Straight", "Straight Flush"},
    "highcard": {"High Card"},
}
MAX_DECK_CARDS = 60   # 卡组膨胀约束：超过后不再买标准牌包（稀释抽牌质量）


class JevLayer:
    def __init__(self, log=None):
        load_env()
        self.log = log
        self.calls = 0
        self.total_latency = 0.0
        self.failed = 0
        self.in_tokens = 0
        self.out_tokens = 0
        self.cost_usd = 0.0
        self._client = None
        self._skip_ante: dict = {}   # M7：每 ante 跳盲次数护栏（与 llm_layer 对齐）
        self._flow: dict = {}        # 动态出牌流：hand → [次数, 累计分]（主力牌型跟踪）
        self._best_single = 0.0      # R15：本局单手最高分（引擎成型度）

    # ------------------------------------------------------------------
    # 动态出牌流（#2）：跟踪各牌型实战均分，主力牌型注入决策
    def note_play(self, bp: dict) -> None:
        h = bp.get("hand")
        if h and h != "-":
            n, s = self._flow.get(h, (0, 0.0))
            self._flow[h] = (n + 1, s + (bp.get("total") or 0))
        self._best_single = max(self._best_single, bp.get("total") or 0)

    def readiness_line(self, gs: dict) -> str:
        """R15 引擎成型度信号：单手最高分 vs Boss 需求曲线（社区"Ante4 检查点"）。"""
        if self._best_single < 1:
            return ""
        boss = next((b.get("score") for b in (gs.get("blinds") or {}).values()
                     if isinstance(b, dict) and b.get("type") == "BOSS"
                     and b.get("status") != "DEFEATED"), None)
        if not boss:
            return ""
        ratio = self._best_single / max(boss, 1)
        line = f"[成型度] 单手最高{self._best_single:.0f} vs 下个Boss需{boss}（{ratio:.0%}）"
        ante = gs.get("ante_num") or 1
        if ante >= 4 and self._best_single < 6000:
            line += " ⚠Ante4+检查点未达标(单手需≥6000), 战力成型优先级最高"
        elif ratio < 0.5:
            line += " ⚠成型不足Boss需求一半, 优先立即战力"
        return line

    def dominant_hand(self) -> str | None:
        best, best_avg = None, 0.0
        for h, (n, s) in self._flow.items():
            if n >= 3 and s / n > best_avg:
                best, best_avg = h, s / n
        return best

    def flow_line(self) -> str:
        rows = sorted(((s / n, n, h) for h, (n, s) in self._flow.items() if n >= 2),
                      reverse=True)[:2]
        if not rows:
            return ""
        parts = []
        for i, (avg, n, h) in enumerate(rows):
            tag = "主力" if i == 0 else "次选"
            parts.append(f"{tag}={h}(均分{avg:.0f}·已打{n}手)")
        return "[出牌流] " + " | ".join(parts) + "（后续购买/升级应围绕主力迭代）"

    def _state_with_flow(self, gs: dict, extra_facts: str = "") -> str:
        text = serialize(gs, extra_facts)
        extra = [x for x in (self.flow_line(), self.readiness_line(gs)) if x]
        return text + ("\n" + "\n".join(extra) if extra else "")

    # ------------------------------------------------------------------
    # 出牌仲裁（#1）：top1/top2 算分接近且牌型不同时，Jev 一票定夺
    def play_arbitrate(self, gs: dict, top3: list[dict]) -> tuple[int, str]:
        """返回 (选top几[0|1], why)。API 失败回落求解器默认（top0）。"""
        t1, t2 = top3[0], top3[1]
        if t2["total"] < 0.9 * t1["total"] or t2["hand"] == t1["hand"]:
            return 0, "求解器分差明确"
        try:
            resp = self.ask(self._state_with_flow(gs), {
                "play_arbit": _choice(
                    "两套打法求解器算分接近，综合牌型等级/小丑协同/后续出牌流迭代价值更优的是",
                    {"a": f"{t1['hand']}={t1['total']:.0f}分",
                     "b": f"{t2['hand']}={t2['total']:.0f}分"}),
            })
            ch = resp.answers["play_arbit"].choice
            if ch in ("a", "b"):
                pick = 0 if ch == "a" else 1
                return pick, f"jev仲裁选{ch}({top3[pick]['hand']})"
            return 0, f"jev仲裁无效({ch})"
        except Exception as e:
            self.failed += 1
            if self.log:
                self.log.log("jev_error", error=str(e), fallback="solver_top1")
            return 0, "仲裁失败→求解器默认"

    @property
    def client(self):
        if self._client is None:
            self._client = _init_client()
        return self._client

    # ------------------------------------------------------------------
    def ask(self, state_text: str, questions: dict):
        """执行一次批量调用并记录（token/成本取 API 返回的实测 usage）。"""
        from typesafe_sdk import Choice, Noul, Score
        t0 = time.time()
        resp = self.client.system_one(state=state_text, questions=questions)
        dt = time.time() - t0
        self.calls += 1
        self.total_latency += dt
        u = getattr(resp, "usage", None)
        in_t = getattr(u, "input_tokens", None) or 0
        out_t = getattr(u, "output_tokens", None) or 0
        cost = pricing.jev_cost_usd(in_t, out_t)
        self.in_tokens += in_t
        self.out_tokens += out_t
        self.cost_usd += cost
        if self.log:
            self.log.jev(state=state_text,
                         questions={k: getattr(q, "instructions", str(q)) for k, q in questions.items()},
                         answers={k: _ans_brief(a) for k, a in resp.answers.items()},
                         latency=round(dt, 2), model=getattr(resp, "model", "jev"),
                         in_tokens=in_t, out_tokens=out_t, cost_usd=cost)
        return resp

    # ------------------------------------------------------------------
    def shop_plan(self, gs: dict) -> list[dict]:
        """返回按优先级排序的购买计划 [{method, params, why}]，外加 reroll 指令。"""
        money = gs.get("money", 0)
        shop_cards = gs.get("shop", {}).get("cards", [])
        jokers_area = gs.get("jokers", {})
        cons_area = gs.get("consumables", {})
        reroll_cost = gs.get("round", {}).get("reroll_cost", 5)

        # 可行性过滤（代码层硬约束）
        candidates = []   # (slot_id, card, kind)
        slots_full = jokers_area.get("count", 0) >= jokers_area.get("limit", 5)
        for i, c in enumerate(shop_cards):
            cost = c.get("cost", {}).get("buy", 999)
            s = c.get("set")
            if s == "JOKER" and slots_full and not _sellable_jokers(jokers_area):
                continue  # 槽满且无槽可腾时跳过（有可卖小丑时仍候选，由卖牌题决定）
            if s in ("PLANET", "TAROT", "SPECTRAL"):
                if cons_area.get("count", 0) >= cons_area.get("limit", 2):
                    continue
                if not buy_ok(c.get("key", ""), gs):   # 无安全用法的消耗牌不买（M2 条件解禁）
                    continue
            # L2：星球不再预过滤（旧守卫在 Jev 答方向之前就把 ante1-2 的星球全灭），
            # 改为答后按方向匹配加/减分
            if s == "BOOSTER":
                if not c.get("key", "").startswith(BUYABLE_PACK_PREFIXES):
                    continue
                if (c.get("key", "").startswith("p_standard")
                        and gs.get("cards", {}).get("count", 52) >= MAX_DECK_CARDS):
                    continue  # 卡组已大，不再稀释
            if s not in ("JOKER", "PLANET", "VOUCHER", "TAROT", "SPECTRAL", "BOOSTER"):
                continue
            candidates.append((f"item{i}", c, s))
        # 重大修复：卡包在独立的 packs 区（gs["packs"]["cards"]），从不在
        # shop.cards 里——旧代码只扫商店区，真实对局从未买过任何包
        # （test_pack 是直接 buy pack=N 绕过商店层，所以测试一直绿）
        for i, c in enumerate((gs.get("packs") or {}).get("cards", [])):
            key = c.get("key", "")
            if not key.startswith(BUYABLE_PACK_PREFIXES):
                continue
            if (key.startswith("p_standard")
                    and gs.get("cards", {}).get("count", 52) >= MAX_DECK_CARDS):
                continue
            candidates.append((f"pack{i}", c, "BOOSTER"))

        vouchers = [(f"voucher{i}", v, "VOUCHER") for i, v in
                    enumerate(gs.get("vouchers", {}).get("cards", []))]
        all_items = candidates + vouchers

        state_text = self._state_with_flow(gs)
        questions: dict = {}

        # 1) 方向识别：单题 Choice（据此混合权重表）
        questions["archetype"] = _choice(
            "当前构筑的核心方向最接近哪一种(将据此调整商店购买权重)", ARCH_CHOICE)

        # 2) 每个候选商品 4 维 Score
        for slot, card, _kind in all_items:
            name = card_name(card)
            price = card.get("cost", {}).get("buy", 0)
            for dim, meaning in DIMS.items():
                questions[f"{slot}__{dim}"] = _score(
                    f"商品[{name}, ${price}] 的{meaning}", RUBRIC[dim])

        # 3) 槽满且有候选小丑时：卖谁腾位（Choice，一个问题定）
        sellable = _sellable_jokers(jokers_area)
        if slots_full and sellable and any(k == "JOKER" for _, _, k in all_items):
            criteria = {f"j{i}": card_name(j) for i, j in enumerate(sellable)}
            questions["sell_which"] = _choice(
                "若要买入新小丑必须先卖掉一个现有小丑, 卖掉损失最小的是", criteria)

        # 3) 重掷判断（H3 反转）：存在性事实题替代旧的价值肯定题——
        # 旧措辞"普遍不高且金币$X时花$Y重掷优于离店"三重保守（复合条件+
        # 肯定花钱动作+错误比较对象），实测 2056 问仅 44 次过 0.5
        questions["shelf_has_goods"] = _noul(
            "当前商店货架上存在至少一件对当前构筑明显值得按其标价买走的商品")

        if not all_items and money < reroll_cost:
            return [{"method": "next_round", "params": {},
                     "why": "无候选且无法重掷"}]

        try:
            resp = self.ask(state_text, questions)
        except Exception as e:
            self.failed += 1
            if self.log:
                self.log.log("jev_error", error=str(e), fallback="naive_shop")
            return _naive_plan(gs)

        a = resp.answers
        # 方向 → Choice 结果（无效答案回落 default）
        arch_ans = a.get("archetype")
        arch = arch_ans.choice if arch_ans and arch_ans.choice in WEIGHTS else "default"
        w_arch = WEIGHTS.get(arch, WEIGHTS["default"])
        w = {k: (1 - BLEND_DEFAULT) * w_arch[k] + BLEND_DEFAULT * WEIGHTS["default"][k]
             for k in DIMS}
        # R16 阶段化权重：社区共识"经济小丑只放 Ante 1-3"——Ante 4+ 经济让位
        # 给倍率成型（economy ×0.3，差额均摊给 scaling/immediate）
        ante = gs.get("ante_num") or 1
        if ante >= 4:
            cut = w["economy"] * 0.7
            w["economy"] -= cut
            w["scaling"] += cut * 0.6
            w["immediate"] += cut * 0.4

        scored = []
        for slot, card, kind in all_items:
            dims = {}
            for dim in DIMS:
                ans = a.get(f"{slot}__{dim}")
                if ans is None:
                    # L3：单维缺答不再整件丢弃（批量 20-40 问丢一件无感知）
                    dims[dim] = {"norm": 0.5, "conf": 0.0, "missing": True}
                    continue
                # H1：量表"4"锚点过极端从未被打出（实测 0 次，3 仅 0.6%），
                # /4 归一把优秀商品压在 0.4-0.55 阈值带——有效天花板改按 3 归一
                dims[dim] = {"norm": min(ans.score or 0, 3) / 3,
                             "conf": getattr(ans, "confidence", 1.0)}
            value = sum(w[dim] * dims[dim]["norm"] for dim in DIMS)
            min_conf = min(dims[dim]["conf"] for dim in DIMS)
            # L2：星球确定性升级按方向答后加权——匹配方向或已打≥2次 +0.10，
            # 方向不符 -0.15（替代旧的进候选前硬过滤）
            if kind == "PLANET":
                hand = PLANET_HAND.get(card.get("key", ""))
                played = (gs.get("hands", {}).get(hand, {}) or {}).get("played", 0)
                dom = self.dominant_hand()
                if hand and hand == dom:
                    value += PLANET_MATCH_BONUS + 0.08   # 主力出牌流再提权
                elif hand and (played >= 2 or hand in ARCH_HANDS.get(arch, set())):
                    value += PLANET_MATCH_BONUS
                elif hand:
                    value -= PLANET_MISMATCH_PENALTY
            # R19 X倍率至上：社区公理"×mult 是乘法贡献"——当前无任何 X 倍率
            # 小丑时（战力警示态），X 倍率候选商品直接提权
            from scoring import XMULT_KEYS
            if card.get("key", "") in XMULT_KEYS and not _has_xmult(gs):
                value += 0.10
            scored.append({"slot": slot, "card": card, "kind": kind, "value": value,
                           "conf": min_conf, "dims": dims})

        plan = []
        card_buy_planned = False
        voucher_buy_planned = False
        # 迭代8教训：超息全局降阈值(0.30)是净负面。
        # 迭代13实测：溢出区间降阈值0.46同样无效（回归3.67 vs 3.83、死钱不降）——
        # 花钱速率被"每商店1卡+1券"结构性封顶，阈值不是瓶颈。
        # 正解：富裕时提高重掷预算（jev_bot 侧），把钱换成搜索机会。
        n_jokers = len(jokers_area.get("cards", []))
        joker_tau = 0.32 if n_jokers < 3 else BUY_VALUE_TAU
        for it in sorted(scored, key=lambda x: -x["value"]):
            price = it["card"].get("cost", {}).get("buy", 0)
            if price > money:
                continue
            tau = joker_tau if it["kind"] == "JOKER" else BUY_VALUE_TAU
            if it["value"] < tau:
                continue
            is_voucher = it["slot"].startswith("voucher")
            # 每次计划最多一张卡牌 + 一张兑换券：购买会移位商店索引/占用槽位，
            # 多张会用到过期索引（实测 -32001 Card index out of range）
            if is_voucher:
                if voucher_buy_planned:
                    continue
            elif card_buy_planned:
                continue
            if it["kind"] == "JOKER" and slots_full:
                # 槽满：死因分析显示深局常5张满员且囤钱——放宽换将门槛
                if it["value"] < 0.50 or "sell_which" not in a:
                    continue
                sell_key = a["sell_which"].choice
                if not sell_key or not sell_key.startswith("j"):
                    continue
                plan.append({"method": "sell", "params": {"joker": int(sell_key[1:])},
                             "why": f"腾位给 {it['card'].get('key')} "
                                    f"(value={it['value']:.2f}, jev卖牌选择={sell_key})"})
                money += sellable[int(sell_key[1:])].get("cost", {}).get("sell", 1)
                slots_full = False
            if is_voucher:
                method, params = "buy", {"voucher": int(it["slot"][7:])}
                voucher_buy_planned = True
            elif it["slot"].startswith("pack"):
                method, params = "buy", {"pack": int(it["slot"][4:])}
                card_buy_planned = True  # 买包即开包，同样使货架/索引位移
            elif it["kind"] == "BOOSTER":
                method, params = "buy", {"pack": int(it["slot"][4:])}
                card_buy_planned = True  # 兼容旧 slot 命名
            else:
                method, params = "buy", {"card": int(it["slot"][4:])}
                card_buy_planned = True
            plan.append({"method": method, "params": params,
                         "why": f"{it['card'].get('key')} value={it['value']:.2f} "
                                f"conf={it['conf']:.2f} arch={arch}"})
            money -= price

        # 重掷（H3+H4 反转）：货架存在性判断为"没有值得买的货"(noul<0.45)且钱够 → 掷。
        # 与 `not plan` 解耦：只看本轮是否真的买了卡/券（卖牌腾位不算花钱）；
        # 旧版阈值 0.5/0.6 落在 noul 分布死区，全部历史仅触发过 11 次
        if (not card_buy_planned and not voucher_buy_planned
                and money >= reroll_cost + 3):
            n = getattr(a.get("shelf_has_goods"), "noul", None)
            if n is not None and n < 0.45:
                plan.append({"method": "reroll", "params": {},
                             "why": f"货架无值得买的货(jev noul={n:.2f}) → 重掷"})
        return plan

    # ------------------------------------------------------------------
    def pack_pick(self, gs: dict) -> tuple[int | None, str]:
        """开包：一次 Choice 问"对当前构筑最有价值的一张"。返回 (下标|None, why)。

        无安全用法的卡（NO_BUY，如死亡/恶灵等）不进入候选（保留原始下标映射），
        全被滤掉则跳过整包。M2 条件解禁后按 buy_ok 放行。
        """
        pack_cards = gs.get("pack", {}).get("cards", [])
        entries = [(i, c) for i, c in enumerate(pack_cards)
                   if buy_ok(c.get("key", ""), gs)]
        if not entries:
            return None, "包内无安全可选卡 → 跳过"
        state_text = self._state_with_flow(gs)
        criteria = {f"p{i}": card_name(c) for i, c in entries}
        try:
            resp = self.ask(state_text, {
                "pick": _choice("开包选择:对当前构筑(小丑/牌型等级/商店经济)最有价值的一张是", criteria),
            })
            a = resp.answers["pick"]
            ch = a.choice
            if ch and ch.startswith("p") and ch[1:].isdigit() and int(ch[1:]) < len(pack_cards):
                return int(ch[1:]), (f"jev choice {pack_cards[int(ch[1:])].get('key')} "
                                     f"conf={getattr(a, 'confidence', 0):.2f}")
            return None, f"jev 选择无效({ch}) → 跳过"
        except Exception as e:
            self.failed += 1
            if self.log:
                self.log.log("jev_error", error=str(e), fallback="pack_skip")
            return None, "jev_failed → 跳过"

    # ------------------------------------------------------------------
    def blind_decision(self, gs: dict) -> tuple[str, str]:
        """返回 ("select"|"skip", why)。求解器能过/不能跳过时不调 Jev。"""
        facts = solver_facts(gs)
        # 待打盲注：BLIND_SELECT 时状态是 SELECT，进行中是 CURRENT
        blind = next((b for b in gs.get("blinds", {}).values()
                      if isinstance(b, dict) and b.get("status") in ("CURRENT", "SELECT")), None)
        btype = blind.get("type", "SMALL") if blind else "SMALL"

        if btype == "BOSS":
            return "select", "boss blind 不可跳过"
        if facts.get("can_clear"):
            return "select", f"solver_can_clear={facts.get('can_clear')}"

        try:
            # M7：存在性问法替代价值肯定题——旧措辞"跳过更合理"实测 noul 落在
            # 0.44-0.64 永不过 0.65 阈值；附 tag 价值分级辅助判断
            ante = gs.get("ante_num")
            if self._skip_ante.get(ante, 0) >= 1:
                return "select", "skip护栏: 本ante已跳过1盲(防连跳直冲Boss)"
            # M7.1 早期禁跳（JEVATRO2实证：ante1跳小盲→少一轮收入/牌型升级→
            # 护栏强制打大盲→Boss面前战力不足、$24未转化而死）——ante1-2 的
            # 回合本身就是收入与升级机会，跳了只会让后面的盲更难打
            if (ante or 1) <= 2:
                return "select", "早期不跳(ante1-2回合=收入+升级机会)"
            tag = blind.get("tag_name", "奖励tag") if blind else "tag"
            tag_val = tag_value(tag)
            tag_note = f"{tag}({tag_val})" if tag_val else tag
            resp = self.ask(self._state_with_flow(gs, facts["text"]), {
                "can_pass": _noul(
                    f"结合手牌/小丑/牌型等级，当前战力有较大概率通过该盲注"
                    f"(求解器估算: {facts['text']})"),
            })
            n = resp.answers["can_pass"].noul
            if n < 0.45:
                # M7.2 标签价值门槛：跳盲=放弃回合收入，只有高价值标签才回本
                # （wiki 战略原则：跳盲只在标签值回票价时划算）
                if tag_val not in ("高价值", "较高价值"):
                    return "select", (f"jev难过关(noul={n:.2f})但标签价值不足"
                                      f"({tag_val or '?'}) → 仍挑战")
                self._skip_ante[ante] = self._skip_ante.get(ante, 0) + 1
                return "skip", f"jev 判定难过关(noul={n:.2f}) → 跳过换{tag_note}"
            return "select", f"jev 判定可过关(noul={n:.2f})"
        except Exception as e:
            self.failed += 1
            if self.log:
                self.log.log("jev_error", error=str(e), fallback="select")
            return "select", "jev_failed"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _noul(instructions):
    from typesafe_sdk import Noul
    return Noul(instructions=instructions)


def _choice(instructions, criteria):
    from typesafe_sdk import Choice
    return Choice(instructions=instructions, criteria=criteria)


def _sellable_jokers(jokers_area: dict) -> list[dict]:
    """可卖小丑（排除永恒 eternal 标记）。"""
    out = []
    for j in jokers_area.get("cards", []):
        m = j.get("modifier")
        mods = set(m) if isinstance(m, list) else set()
        if "eternal" in mods:
            continue
        out.append(j)
    return out


def _has_xmult(gs: dict) -> bool:
    """当前是否已持有 X 倍率小丑（R19 提权条件）。"""
    from scoring import XMULT_KEYS
    return any(j.get("key", "") in XMULT_KEYS
               for j in (gs.get("jokers") or {}).get("cards", []))


def _score(instructions, criteria):
    from typesafe_sdk import Score
    return Score(instructions=instructions, criteria=criteria)


def _ans_brief(a) -> dict:
    d = {"type": getattr(a, "type", None)}
    for f in ("noul", "choice", "score", "confidence", "probabilities"):
        v = getattr(a, f, None)
        if v is not None:
            d[f] = v
    return d


def _naive_plan(gs: dict) -> list[dict]:
    """Jev 不可用时的回退：买得起的第一张小丑/兑换券。"""
    money = gs.get("money", 0)
    shop_cards = gs.get("shop", {}).get("cards", [])
    jokers = gs.get("jokers", {})
    if jokers.get("count", 0) < jokers.get("limit", 5):
        for i, c in enumerate(shop_cards):
            if c.get("set") == "JOKER" and c.get("cost", {}).get("buy", 999) <= money:
                return [{"method": "buy", "params": {"card": i}, "why": "naive_fallback"}]
    for i, c in enumerate(shop_cards):
        if c.get("set") == "VOUCHER" and c.get("cost", {}).get("buy", 999) <= money:
            return [{"method": "buy", "params": {"voucher": i}, "why": "naive_fallback"}]
    return []
