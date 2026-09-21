"""手动测试 start 的完整错误信息。"""
from client import BalatroClient

bot = BalatroClient()
gs = bot.gamestate()
print("state:", gs.get("state"))
try:
    r = bot.call("start", deck="RED", stake="WHITE", seed="JEVATRO1")
    print("start OK:", r.get("state"), "seed=", r.get("seed"))
except Exception as e:
    print("start FAIL:", repr(e))
    # 不带 seed 再试
    try:
        r2 = bot.call("start", deck="RED", stake="WHITE")
        print("start(no seed) OK:", r2.get("state"), "seed=", r2.get("seed"))
    except Exception as e2:
        print("start(no seed) FAIL:", repr(e2))
