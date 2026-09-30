"""传统 LLM 决策层（OpenAI 兼容接口；当前后端：DeepSeek deepseek-flash）。

一次商店决策一次 chat 调用（与 Jev 的批量单调用对等）；输出 JSON 容错解析；
失败回退 naive 策略。token 用量与延迟全程记录（kind="llm"）。
后端在 .env 配置（LLM_BASE/LLM_API_KEY/LLM_MODEL，兼容旧 ZHIPU_* 变量名）。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

from jev_layer import load_env, _naive_plan
from serializer import card_name, serialize, solver_facts
from solver import best_play

import pricing

SYSTEM = (
    "你是小丑牌(Balatro)的商店决策引擎。只输出一个JSON对象,禁止任何其他文字、"
    "解释或markdown代码块标记。"
)


class LlmLayer:
    def __init__(self, log=None, model: str | None = None, base: str | None = None):
        load_env()
        self.log = log
        self.model = (model or os.environ.get("LLM_MODEL")
                      or os.environ.get("ZHIPU_MODEL", "deepseek-flash"))
        self.base = (base or os.environ.get("LLM_BASE")
                     or os.environ.get("ZHIPU_BASE", "https://api.deepseek.com"))
        self.key = (os.environ.get("LLM_API_KEY")
                    or os.environ.get("ZHIPU_API_KEY", ""))
        self.calls = 0
        self.total_latency = 0.0
        self.in_tokens = 0
        self.out_tokens = 0
        self.in_hit_tokens = 0
        self.in_miss_tokens = 0
        self.cost_usd = 0.0
        self.failed = 0
        self._skip_ante: dict[int, int] = {}   # 每个 ante 的跳盲次数护栏

    # ------------------------------------------------------------------
    def _chat(self, user: str, max_tokens: int = 3000) -> str:
        """思考耗尽治理：content 空时从 reasoning_content 尾部提取 JSON 草稿；
        仍无输出则预算翻倍重试一次（两轮都空才回退）——空回复同样计费，不能白扔。"""
        for attempt in range(2):
            budget = max_tokens if attempt == 0 else max_tokens * 2
            body = {
                "model": self.model,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": user}],
                "max_tokens": budget,
                "temperature": 0.2,
            }
            req = urllib.request.Request(
                self.base + "/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json"},
            )
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            dt = time.time() - t0
            msg = (d.get("choices") or [{}])[0].get("message", {})
            content = msg.get("content") or ""
            src = "content"
            if not content.strip():
                # 思考吃满预算：content 空、思考在 reasoning_content——其末尾常已
                # 草拟出目标 JSON，逐个候选尝试解析而不是直接放弃（费用已发生）
                rc = msg.get("reasoning_content") or ""
                cands = re.findall(r"\{[^{}]*\}", rc)
                for c in reversed(cands):
                    try:
                        json.loads(c)
                        content, src = c, "reasoning草稿"
                        break
                    except json.JSONDecodeError:
                        continue
                if not content and attempt == 0:
                    continue          # 翻倍预算重试一次
            self.calls += 1
            self.total_latency += dt
            u = d.get("usage", {})
            in_t = u.get("prompt_tokens", 0)
            out_t = u.get("completion_tokens", 0)
            # DeepSeek 返回缓存命中/未命中拆分；其他兼容后端缺省按全部未命中计
            hit = u.get("prompt_cache_hit_tokens", 0) or 0
            miss = u.get("prompt_cache_miss_tokens", in_t - hit) or 0
            if hit + miss == 0:
                miss = in_t
            cost = pricing.llm_cost_usd(miss, hit, out_t, model=self.model)
            self.in_tokens += in_t
            self.out_tokens += out_t
            self.in_hit_tokens += hit
            self.in_miss_tokens += miss
            self.cost_usd += cost
            if self.log:
                self.log.llm(model=self.model, prompt=user, reply=content,
                             latency=round(dt, 2), in_tokens=in_t,
                             out_tokens=out_t, in_hit_tokens=hit, in_miss_tokens=miss,
                             cost_usd=cost)
            return content
        return ""

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    def shop_plan(self, gs: dict) -> list[dict]:
        money = gs.get("money", 0)
        shop_cards = gs.get("shop", {}).get("cards", [])
        jokers_area = gs.get("jokers", {})
        cons_area = gs.get("consumables", {})
        slots_full = jokers_area.get("count", 0) >= jokers_area.get("limit", 5)

        candidates = []
        for i, c in enumerate(shop_cards):
            s = c.get("set")
            if s == "JOKER" and slots_full:
                continue
            if s in ("PLANET", "TAROT", "SPECTRAL") and \
                    cons_area.get("count", 0) >= cons_area.get("limit", 2):
                continue
            if s not in ("JOKER", "PLANET", "VOUCHER", "TAROT", "SPECTRAL", "BOOSTER"):
                continue
            candidates.append((f"item{i}", c))
        # 卡包在独立 packs 区（重大修复：与 Jev 层同步，此前 LLM 也从未见过包）
        for i, c in enumerate((gs.get("packs") or {}).get("cards", [])):
            key = c.get("key", "")
            if key.startswith(("p_buffoon", "p_standard", "p_celestial",
                               "p_tarot", "p_spectral")):
                candidates.append((f"pack{i}", c))
        vouchers = [(f"voucher{i}", v)
                    for i, v in enumerate(gs.get("vouchers", {}).get("cards", []))]
        all_items = candidates + vouchers
        if not all_items:
            return []

        lines = [serialize(gs), "",
                 f"金币${money}, 小丑槽 {jokers_area.get('count')}/{jokers_area.get('limit')}。"
                 "可选购买项(按优先级排序, 可多选, 不可透支金币):"]
        for slot, card in all_items:
            lines.append(f"  {slot}: {card_name(card)} ${card.get('cost', {}).get('buy', '?')}")

        user = "\n".join(lines) + (
            '\n输出JSON: {"buys":["item0","voucher0"],"reason":"<=30字"} '
            '(buys按优先级排序, 不值得买则空数组)')
        try:
            out = self._parse_json(self._chat(user))
        except Exception as e:
            self.failed += 1
            if self.log:
                self.log.log("llm_error", error=str(e)[:200], fallback="naive_shop")
            return _naive_plan(gs)
        if not out or not isinstance(out.get("buys"), list):
            self.failed += 1
            return _naive_plan(gs)

        slot_map = dict(all_items)
        plan = []
        for slot in out["buys"]:
            if not isinstance(slot, str) or slot not in slot_map:
                continue
            card = slot_map[slot]
            price = card.get("cost", {}).get("buy", 0)
            if price > money:
                continue
            if slot.startswith("voucher"):
                params = {"voucher": int(slot[7:])}
            elif slot.startswith("pack"):
                params = {"pack": int(slot[4:])}
            else:
                params = {"card": int(slot[4:])}
            plan.append({"method": "buy", "params": params,
                         "why": f"llm {slot} {card.get('key')}"})
            money -= price
        # 一次计划同样只买一张卡防索引位移（与 Jev 层一致的约束）
        card_buys = [p for p in plan if "card" in p["params"]]
        voucher_buys = [p for p in plan if "voucher" in p["params"]]
        return card_buys[:1] + voucher_buys[:1]

    # ------------------------------------------------------------------
    def blind_decision(self, gs: dict) -> tuple[str, str]:
        facts = solver_facts(gs)
        blind = next((b for b in gs.get("blinds", {}).values()
                      if isinstance(b, dict) and b.get("status") in ("CURRENT", "SELECT")), None)
        btype = blind.get("type", "SMALL") if blind else "SMALL"
        if btype == "BOSS":
            return "select", "boss 不可跳过"
        if facts.get("can_clear"):
            return "select", "solver 可过"
        # 护栏：连跳两个盲会无经济直冲 Boss（sanity 实测教训），每 ante 最多跳 1 个
        ante = gs.get("ante_num", 0)
        if self._skip_ante.get(ante, 0) >= 1:
            return "select", "护栏: 本ante已跳过1个盲"
        user = (serialize(gs, facts["text"]) +
                '\n求解器判断难以过关。输出JSON: {"skip": true或false, "reason":"<=20字"}')
        try:
            out = self._parse_json(self._chat(user))
            skip = bool(out and out.get("skip"))
            if skip:
                self._skip_ante[ante] = self._skip_ante.get(ante, 0) + 1
            return ("skip" if skip else "select"), f"llm skip={skip}"
        except Exception as e:
            self.failed += 1
            return "select", f"llm_failed {str(e)[:60]}"

    # ------------------------------------------------------------------
    def pack_pick(self, gs: dict) -> tuple[int | None, str]:
        pack_cards = gs.get("pack", {}).get("cards", [])
        if not pack_cards:
            return None, "空包"
        lines = [serialize(gs), "", "开包可选:"]
        for i, c in enumerate(pack_cards):
            lines.append(f"  p{i}: {card_name(c)}")
        user = "\n".join(lines) + '\n输出JSON: {"pick":"p0","reason":"<=20字"} (不想选则 pick:null)'
        try:
            out = self._parse_json(self._chat(user))
            pick = out.get("pick") if out else None
            if isinstance(pick, str) and pick.startswith("p") and pick[1:].isdigit():
                idx = int(pick[1:])
                if idx < len(pack_cards):
                    return idx, f"llm {pack_cards[idx].get('key')}"
            return None, "llm 跳过"
        except Exception as e:
            self.failed += 1
            return None, f"llm_failed {str(e)[:60]}"
