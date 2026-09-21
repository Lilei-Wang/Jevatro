"""消耗牌买/用链路集成测试：用 debug add 注入，验证 use_policy 的目标选择。"""
from client import BalatroClient
from logger import RunLogger
import use_policy

bot = BalatroClient()
assert bot.wait_online(tries=3), "游戏未运行"
log = RunLogger("ittest")

gs = bot.gamestate()
if gs.get("state") != "MENU":
    gs = bot.call("menu")
gs = bot.call("start", deck="RED", stake="WHITE", seed="USETEST1")
print("state:", gs["state"])

if gs["state"] == "BLIND_SELECT":
    gs = bot.call("select")
print("state:", gs["state"], "hand:", len(gs["hand"]["cards"]))

# 1) 注入强化塔罗(皇后: 2张→Mult卡) 并在出牌阶段使用
gs = bot.call("add", key="c_empress")
print("注入 c_empress, 消耗区:", [c["key"] for c in gs["consumables"]["cards"]])
before_mods = [c["modifier"] for c in gs["hand"]["cards"]]
gs = use_policy.apply(bot, log, gs, phase="HAND")
after_mods = [c["modifier"] for c in gs["hand"]["cards"]]
enhanced = sum(1 for m in after_mods if m and m != [])
print(f"强化后带修饰的手牌数: {enhanced} (之前 {sum(1 for m in before_mods if m and m != [])})")
assert enhanced >= sum(1 for m in before_mods if m and m != []) + 1, "强化未生效"

# 2) 注入星球(土星: 升顺子) 并在商店使用
gs = bot.call("menu")
gs = bot.call("start", deck="RED", stake="WHITE", seed="USETEST2")
gs = bot.call("select")
gs = bot.call("play", cards=[0])
# 打完小盲可能进入下一状态，循环打到 ROUND_EVAL -> cash_out
for _ in range(30):
    if gs.get("state") in ("ROUND_EVAL", "SHOP", "GAME_OVER"):
        break
    gs = bot.gamestate()
if gs.get("state") == "ROUND_EVAL":
    gs = bot.call("cash_out")
print("state:", gs["state"])
gs = bot.call("add", key="c_saturn")
straight_before = gs["hands"]["Straight"]["level"]
gs = use_policy.apply(bot, log, gs, phase="SHOP")
gs = bot.gamestate()
straight_after = gs["hands"]["Straight"]["level"]
print(f"顺子等级 {straight_before} -> {straight_after}")
assert straight_after == straight_before + 1, "星球未生效"

log.close()
print("INTEGRATION TEST PASS")
