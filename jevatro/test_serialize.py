"""serialize 冒烟测试：真实 gamestate 跑一遍序列化。"""
from client import BalatroClient
from serializer import serialize

bot = BalatroClient()
gs = bot.gamestate()
text = serialize(gs)
print(text[:800])
print("---")
print("SERIALIZE OK,", len(text), "chars")
