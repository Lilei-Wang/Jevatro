"""开包链路集成测试：直接购买商店现成的包 → Jev Choice 选牌。"""
from client import BalatroClient
from jev_layer import JevLayer
from logger import RunLogger
from naive_bot import act
from solver import best_play

bot = BalatroClient()
assert bot.wait_online(tries=3), "游戏未运行"
log = RunLogger("packtest")
jev = JevLayer(log)

gs = bot.gamestate()
if gs.get("state") != "MENU":
    gs = bot.call("menu")
gs = bot.call("start", deck="RED", stake="WHITE", seed="PACKTEST2")
gs = bot.call("select")

# 打到商店（debug set 直接过小盲——本测试只验证开包链路）
for _ in range(60):
    if gs.get("state") in ("ROUND_EVAL", "SHOP", "GAME_OVER"):
        break
    if gs.get("state") == "SELECTING_HAND":
        need = best_play(gs).get("need", 300)
        gs = bot.call("set", chips=max(need, 1))
        gs = bot.call("play", cards=[0, 1, 2, 3, 4])
    gs = bot.gamestate()
if gs.get("state") == "ROUND_EVAL":
    gs = bot.call("cash_out")
print("shop state:", gs.get("state"))

packs = (gs.get("packs") or {}).get("cards", [])
print("商店包:", [c.get("key") for c in packs])
SUPPORTED = ("p_buffoon", "p_standard", "p_celestial")
idx = next((i for i, c in enumerate(packs)
            if c.get("key", "").startswith(SUPPORTED)), None)
assert idx is not None, "商店无受支持的包（本次随机只刷了塔罗/幻灵包），换种子重跑"

gs = act(bot, log, gs, "buy", pack=idx)
print("after buy state:", gs.get("state"),
      "pack options:", [c.get("key") for c in (gs.get("pack") or {}).get("cards", [])])

assert gs.get("state") == "SMODS_BOOSTER_OPENED", "买包后未进入开包状态"
before = {"jokers": (gs.get("jokers") or {}).get("count", 0),
          "consumables": (gs.get("consumables") or {}).get("count", 0)}
pick, why = jev.pack_pick(gs)
print(f"pack_pick → {pick} ({why})")
assert pick is not None, "Jev 未选出卡"
gs = act(bot, log, gs, "pack", card=pick, extra={"why": why})
after = {"jokers": (gs.get("jokers") or {}).get("count", 0),
         "consumables": (gs.get("consumables") or {}).get("count", 0)}
print(f"小丑 {before['jokers']}→{after['jokers']}, 消耗牌 {before['consumables']}→{after['consumables']},"
      f" state={gs.get('state')}")
assert (after["jokers"] > before["jokers"]
        or after["consumables"] > before["consumables"]
        or gs.get("state") == "SHOP"), "开包选择未产生效果"
log.close()
print("PACK TEST PASS")
