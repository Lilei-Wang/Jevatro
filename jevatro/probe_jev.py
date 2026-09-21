"""探测 typesafe-sdk 接口签名 + 用真实 key 做一次最小调用。"""
import inspect
import os

from typesafe_sdk import TypeSafeClient, Choice, Score, Noul

print("== Choice fields ==", inspect.signature(Choice.__init__))
print("== Score fields ==", inspect.signature(Score.__init__))
print("== Noul fields ==", inspect.signature(Noul.__init__))
print("== TypeSafeClient ==", inspect.signature(TypeSafeClient.__init__))
print("== system_one ==", inspect.signature(TypeSafeClient.system_one))

# 读 .env
key = None
for line in open(".env", encoding="utf-8"):
    if line.startswith("TYPESAFE_API_KEY="):
        key = line.strip().split("=", 1)[1]
os.environ["TYPESAFE_API_KEY"] = key
print("key loaded:", key[:16] + "..." + key[-6:])

client = TypeSafeClient()
resp = client.system_one(
    state="Balatro(小丑牌)是一款扑克构建类肉鸽游戏。当前局面: 手牌有 黑桃A 红桃3 方块3, 已有小丑'Joker'(+4 Mult)。",
    questions={
        "is_flush_build": Noul(instructions="当前构筑方向是同花(Flush)流派"),
        "buy_joker": Choice(
            instructions="是否应该购买新小丑来提升战力",
            criteria={"yes": "小丑数量不足,需要补充", "no": "小丑已足够或金币紧张"},
        ),
        "hand_strength": Score(
            instructions="当前手牌强度的紧迫程度",
            criteria=["很低", "较低", "中等", "较高", "很高"],
        ),
    },
)
for k, a in resp.answers.items():
    print(k, "->", a)
