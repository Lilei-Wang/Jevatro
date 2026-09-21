"""打印真实 gamestate 的关键结构，用于对齐 schema。"""
import json
from client import BalatroClient

bot = BalatroClient()
gs = bot.gamestate()
print("state:", gs.get("state"))
if gs.get("state") == "SELECTING_HAND":
    c = gs["hand"]["cards"][0]
    print("card[0] =", json.dumps(c, ensure_ascii=False, indent=1))
    print("round =", json.dumps(gs.get("round"), ensure_ascii=False))
    b = gs.get("blinds", {})
    print("blinds =", json.dumps(b, ensure_ascii=False)[:600])
    print("jokers area =", json.dumps(gs.get("jokers"), ensure_ascii=False)[:400])
    print("hand area keys =", list(gs.get("hand", {}).keys()))
else:
    print(json.dumps(gs, ensure_ascii=False, indent=1)[:1500])
