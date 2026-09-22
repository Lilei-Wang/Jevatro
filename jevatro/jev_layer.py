"""Jev 决策层（Tier 1）：商店 Composite Scoring + 盲注 Noul + 方向识别 fan-out。

所有题目混装进一次 system_one 调用（并行隔离执行），置信度不足走保守默认。
Jev API 失败时回退到 naive 策略，保证 bot 永远能继续打。
"""
from __future__ import annotations

import os
import time

from serializer import card_name, serialize, solver_facts
from solver import best_play
from use_policy import NO_BUY

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
    "economy":  "该商品对金钱/利息循环的贡献",
    "immediate": "该商品对接下来1-2个盲注得分能力的提升程度",
}
RUBRIC = {
    "synergy":  ["0 与现有构筑零交互甚至冲突", "1 略相关但方向不符", "2 中性填充",
                 "3 明确加强现有方向", "4 核心拼图,改变战力曲线"],
    "scaling":  ["0 无成长", "1 一次性收益", "2 轻微成长", "3 每轮稳定成长", "4 复利式成长"],
    "economy":  ["0 纯花钱无回报", "1 略亏", "2 回本", "3 产出大于成本", "4 直接利息引擎"],
    "immediate": ["0 对得分完全无助", "1 略有帮助", "2 有一定帮助", "3 显著提升近期得分",
                  "4 立刻改变能否过关"],
}

BUY_VALUE_TAU = 0.40    # 综合价值阈值（置信度仅记录不门控：实测 conf=0.0 是"无信号"非"不可靠"）
ARCHETYPE_TAU = 0.50    # 方向识别的 noul 阈值
BLEND_DEFAULT = 0.5     # 方向权重与 default 各占一半（防止 econ 方向过度稀释战力权重）

# 可买的卡包：小丑包(加槽)/标准牌包(进牌组)/天体包(星球即用)；
# 塔罗包/幻灵包开包需即时选目标，暂不买
BUYABLE_PACK_PREFIXES = ("p_buffoon", "p_standard", "p_celestial")


class JevLayer:
    def __init__(self, log=None):
        load_env()
        self.log = log
        self.calls = 0
        self.total_latency = 0.0
        self.failed = 0
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = _init_client()
        return self._client

    # ------------------------------------------------------------------
    def ask(self, state_text: str, questions: dict):
        """执行一次批量调用并记录。失败抛异常，由调用方回退。"""
        from typesafe_sdk import Choice, Noul, Score
        t0 = time.time()
        resp = self.client.system_one(state=state_text, questions=questions)
        dt = time.time() - t0
        self.calls += 1
        self.total_latency += dt
        if self.log:
            self.log.jev(state=state_text,
                         questions={k: getattr(q, "instructions", str(q)) for k, q in questions.items()},
                         answers={k: _ans_brief(a) for k, a in resp.answers.items()},
                         latency=round(dt, 2))
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
                if c.get("key") in NO_BUY:   # 无安全用法的消耗牌不买
                    continue
            if s == "BOOSTER":
                if not c.get("key", "").startswith(BUYABLE_PACK_PREFIXES):
                    continue  # 塔罗包/幻灵包暂不买
            if s not in ("JOKER", "PLANET", "VOUCHER", "TAROT", "SPECTRAL", "BOOSTER"):
                continue
            candidates.append((f"item{i}", c, s))

        vouchers = [(f"voucher{i}", v, "VOUCHER") for i, v in
                    enumerate(gs.get("vouchers", {}).get("cards", []))]
        all_items = candidates + vouchers

        state_text = serialize(gs)
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

        # 3) 重掷判断（商店无货时的备选）
        questions["reroll_worth"] = _noul(
            f"当前商店候选的综合价值普遍不高且金币${money}(重掷费${reroll_cost})时,"
            f"花${reroll_cost}重掷商店优于直接离店")

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

        scored = []
        for slot, card, kind in all_items:
            dims = {}
            for dim in DIMS:
                ans = a.get(f"{slot}__{dim}")
                if ans is None:
                    dims[dim] = None
                    continue
                dims[dim] = {"norm": (ans.score or 0) / 4, "conf": getattr(ans, "confidence", 1.0)}
            if any(d is None for d in dims.values()):
                continue
            value = sum(w[dim] * dims[dim]["norm"] for dim in DIMS)
            min_conf = min(dims[dim]["conf"] for dim in DIMS)
            scored.append({"slot": slot, "card": card, "kind": kind, "value": value,
                           "conf": min_conf, "dims": dims})

        plan = []
        card_buy_planned = False
        voucher_buy_planned = False
        # 迭代8教训：超息时全局降阈值(0.30)是净负面——死时金币$6且ante反降,
        # 钱砸在平庸小丑上; 囤钱的正解是买"确定性升级"(星球/好塔罗)而非泛买。
        # 故只保留早期小丑稀缺放宽, 富裕时不降阈值(交给state经济警示让Jev自己权衡)
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
            elif it["kind"] == "BOOSTER":
                method, params = "buy", {"pack": int(it["slot"][4:])}
                card_buy_planned = True  # 买包即开包，同样使商店索引位移
            else:
                method, params = "buy", {"card": int(it["slot"][4:])}
                card_buy_planned = True
            plan.append({"method": method, "params": params,
                         "why": f"{it['card'].get('key')} value={it['value']:.2f} "
                                f"conf={it['conf']:.2f} arch={arch}"})
            money -= price

        # 重掷：没买到东西时——钱宽裕（>重掷费+10）放宽到 noul>0.5，
        # 钱紧维持 noul>0.6（死因分析：深局常有钱没处花）
        if not plan and money >= reroll_cost + 3:
            thr = 0.5 if money >= reroll_cost + 10 else 0.6
            if getattr(a.get("reroll_worth"), "noul", 0) > thr:
                plan.append({"method": "reroll", "params": {},
                             "why": f"jev reroll noul={a['reroll_worth'].noul:.2f}"})
        return plan

    # ------------------------------------------------------------------
    def pack_pick(self, gs: dict) -> tuple[int | None, str]:
        """开包：一次 Choice 问"对当前构筑最有价值的一张"。返回 (下标|None, why)。"""
        pack_cards = gs.get("pack", {}).get("cards", [])
        if not pack_cards:
            return None, "空包跳过"
        state_text = serialize(gs)
        criteria = {f"p{i}": card_name(c) for i, c in enumerate(pack_cards)}
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
            resp = self.ask(serialize(gs, facts["text"]), {
                "skip_better": _noul(
                    f"求解器判断按最优打法也难以过关({facts['text']})。"
                    f"跳过该盲注(换取{blind.get('tag_name','奖励tag') if blind else 'tag'})"
                    f"比强行挑战更合理"),
            })
            n = resp.answers["skip_better"].noul
            action = "skip" if n > 0.65 else "select"
            return action, f"jev skip noul={n:.2f}"
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
