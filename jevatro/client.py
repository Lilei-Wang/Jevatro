"""BalatroBot JSON-RPC 2.0 client."""
from __future__ import annotations

import time
import requests

DEFAULT_URL = "http://127.0.0.1:12346"


class BalatroError(RuntimeError):
    def __init__(self, code: int, message: str, data: dict | None = None):
        super().__init__(f"[{code}] {message} ({data})")
        self.code = code
        self.data = data or {}


class BalatroClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 60.0):
        self.url = url
        self.timeout = timeout
        self._id = 0

    def call(self, method: str, **params) -> dict:
        self._id += 1
        r = requests.post(
            self.url,
            json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
            timeout=self.timeout,
        )
        payload = r.json()
        if "error" in payload:
            raise BalatroError(
                payload["error"].get("code", -1),
                payload["error"].get("message", "unknown"),
                payload["error"].get("data"),
            )
        return payload["result"]

    # ---- 便捷封装 -----------------------------------------------------------
    def health(self) -> dict:
        return self.call("health")

    def gamestate(self) -> dict:
        return self.call("gamestate")

    def wait_online(self, tries: int = 30, delay: float = 1.0) -> bool:
        for _ in range(tries):
            try:
                return self.health().get("status") == "ok"
            except Exception:
                time.sleep(delay)
        return False

    def wait_state(self, expected: set[str], tries: int = 40, delay: float = 0.5) -> dict:
        """轮询直到进入期望状态之一，返回该状态。"""
        for _ in range(tries):
            gs = self.gamestate()
            if gs.get("state") in expected:
                return gs
            time.sleep(delay)
        return self.gamestate()
