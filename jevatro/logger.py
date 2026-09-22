"""JSONL 逐决策日志。"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"


def _brief(gs: dict) -> dict:
    """状态摘要：完整 state 另存，这里只留关键字段。"""
    return {
        "state": gs.get("state"),
        "ante": gs.get("ante_num"),
        "round": gs.get("round_num"),
        "money": gs.get("money"),
        "chips": gs.get("round", {}).get("chips"),
        "hands_left": gs.get("round", {}).get("hands_left"),
        "n_jokers": gs.get("jokers", {}).get("count"),
        "won": gs.get("won"),
    }


class RunLogger:
    def __init__(self, tag: str = "naive"):
        LOG_DIR.mkdir(exist_ok=True)
        fname = f"run_{tag}_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        self.path = LOG_DIR / fname
        self._f = open(self.path, "a", encoding="utf-8")
        self.actions = 0
        self.illegal = 0
        self.t0 = time.time()

    def log(self, kind: str, **kw):
        rec = {"t": round(time.time() - self.t0, 2), "kind": kind, **kw}
        self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._f.flush()

    def jev(self, state: str, questions: dict, answers: dict, latency: float,
            model: str = "", in_tokens: int = 0, out_tokens: int = 0,
            cost_usd: float = 0.0):
        """记录一次 Jev 批量调用（题目/回答/延迟/token/成本全部落盘）。"""
        self.log("jev", state=state, questions=questions,
                 answers=answers, latency=latency, model=model,
                 in_tokens=in_tokens, out_tokens=out_tokens,
                 cost_usd=round(cost_usd, 6))

    def llm(self, model: str, prompt: str, reply: str, latency: float,
            in_tokens: int, out_tokens: int, in_hit_tokens: int = 0,
            in_miss_tokens: int = 0, cost_usd: float = 0.0):
        """记录一次传统 LLM 调用（token 含缓存命中/未命中拆分）。"""
        self.log("llm", model=model, prompt=prompt[:1500], reply=reply[:500],
                 latency=latency, in_tokens=in_tokens, out_tokens=out_tokens,
                 in_hit_tokens=in_hit_tokens, in_miss_tokens=in_miss_tokens,
                 cost_usd=round(cost_usd, 6))

    def action(self, method: str, params: dict, before: dict, after: dict,
               extra: dict | None = None, error: str | None = None):
        self.actions += 1
        if error:
            self.illegal += 1
        self.log("action", method=method, params=params,
                 before=_brief(before), after=_brief(after),
                 error=error, **(extra or {}))

    def finish(self, gs: dict):
        self.log("result", final=_brief(gs), actions=self.actions,
                 illegal=self.illegal, duration=round(time.time() - self.t0, 1))
        self._f.close()

    def close(self):
        self._f.close()
