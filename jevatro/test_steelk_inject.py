"""钢K注入器：等 bot 开局后立即注入 Baron+Mime，让完整决策链实战验证钢K策略。"""
import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def call(method, **params):
    req = urllib.request.Request(
        "http://127.0.0.1:12346/",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                         "params": params}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read()).get("result", {})


print("[injector] 等待对局开始…")
for _ in range(60):
    gs = call("gamestate")
    if gs.get("state") not in ("MENU", None):
        break
    time.sleep(1)
print("[injector] 对局中, 注入 j_baron + j_mime …")
for key in ("j_baron", "j_mime"):
    try:
        call("add", key=key)
        print(f"[injector] ✓ {key}")
    except Exception as e:
        print(f"[injector] ✗ {key}: {str(e)[:80]}")
gs = call("gamestate")
print("[injector] 当前小丑:",
      [c.get("key") for c in (gs.get("jokers") or {}).get("cards", [])])
