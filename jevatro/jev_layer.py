"""Jev 决策层（Tier 1）：商店 Composite Scoring + 盲注 Noul + 方向识别 fan-out。

所有题目混装进一次 system_one 调用（并行隔离执行），置信度不足走保守默认。
Jev API 失败时回退到 naive 策略，保证 bot 永远能继续打。
"""
from __future__ import annotations

import os
import time

from serializer import card_name, serialize, solver_facts
from solver import best_play

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
    "econ":     {"synergy": 0.22, "scaling": 0.25, "economy": 0.38, "immediate": 0.15},
}

ARCHETYPES = {
    "flush":    "当前构筑正走同花(Flush)方向",
    "pair":     "当前构筑正走对子/三条(Pair/Three of a Kind)方向",
    "highcard": "当前构筑正走高牌(High Card)+固定加成小丑方向",
    "straight": "当前构筑正走顺子(Straight)方向",
    "econ":     "当前处于攒钱/经济运营优先阶段(金币偏低或利息优先)",
}

DIMS = {
    "synergy":  "该商品与现有小丑/牌型等级的协同程度",
    "scaling":  "该商品的长期成长性(以本局剩余周目视角)",
    "economy":  "该商品对金钱/利息循环的贡献",
    "immediate": "该商品立刻缓解当前战力缺口(能否过关)的程度",
}
RUBRIC = {
    "synergy":  ["0 与现有构筑零交互甚至冲突", "1 略相关但方向不符", "2 中性填充",
                 "3 明确加强现有方向", "4 核心拼图,改变战力曲线"],
    "scaling":  ["0 无成长", "1 一次性", "2 轻微成长", "3 稳定成长", "4 复利式成长"],
    "economy":  ["0 纯花钱无回报", "1 略亏", "2 回本", "3 产出大于成本", "4 直接利息引擎"],
    "immediate": ["0 无助", "1 微弱", "2 有些帮助", "3 明显", "4 本回合就靠它"],
}

BUY_VALUE_TAU = 0.40    # 综合价值阈值（置信度仅记录不门控：实测 conf=0.0 是"无信号"非"不可靠"）
ARCHETYPE_TAU = 0.50    # 方向识别的 noul 阈值
BLEND_DEFAULT = 0.5     # 方向权重与 default 各占一半（防止 econ 方向过度稀释战力权重）


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
        for i, c in enumerate(shop_cards):
            cost = c.get("cost", {}).get("buy", 999)
            s = c.get("set")
            if s == "JOKER" and jokers_area.get("count", 0) >= jokers_area.get("limit", 5):
                continue
            if s in ("PLANET", "TAROT", "SPECTRAL") and cons_area.get("count", 0) >= cons_area.get("limit", 2):
                continue
            if s not in ("JOKER", "PLANET", "VOUCHER"):   # 本轮迭代: 塔罗/卡包暂不买
                continue
            candidates.append((f"item{i}", c, s))

        vouchers = [(f"voucher{i}", v, "VOUCHER") for i, v in
                    enumerate(gs.get("vouchers", {}).get("cards", []))]
        all_items = candidates + vouchers

        state_text = serialize(gs)
        questions: dict = {}

        # 1) archetype fan-out（Noul 批量）
        for k, desc in ARCHETYPES.items():
            questions[f"arch_{k}"] = _noul(desc)

        # 2) 每个候选商品 4 维 Score
        for slot, card, _kind in all_items:
            name = card_name(card)
            price = card.get("cost", {}).get("buy", 0)
            for dim, meaning in DIMS.items():
                questions[f"{slot}__{dim}"] = _score(
                    f"商品[{name}, ${price}] 的{meaning}", RUBRIC[dim])

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
        # archetype → argmax（超过阈值的最高项，否则 default）
        arch = "default"
        best_arch = max(ARCHETYPES, key=lambda k: a[f"arch_{k}"].noul)
        if a[f"arch_{best_arch}"].noul >= ARCHETYPE_TAU:
            arch = best_arch
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
        for it in sorted(scored, key=lambda x: -x["value"]):
            price = it["card"].get("cost", {}).get("buy", 0)
            if price > money:
                continue
            if it["value"] < BUY_VALUE_TAU:
                continue
            if it["slot"].startswith("voucher"):
                method, params = "buy", {"voucher": int(it["slot"][7:])}
            else:
                method, params = "buy", {"card": int(it["slot"][4:])}
            plan.append({"method": method, "params": params,
                         "why": f"{it['card'].get('key')} value={it['value']:.2f} "
                                f"conf={it['conf']:.2f} arch={arch}"})
            money -= price

        # 重掷（仅当没买到东西且 Jev 认为值得）
        if not plan and money >= reroll_cost + 3:
            if getattr(a.get("reroll_worth"), "noul", 0) > 0.6:
                plan.append({"method": "reroll", "params": {},
                             "why": f"jev reroll noul={a['reroll_worth'].noul:.2f}"})
        return plan

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
