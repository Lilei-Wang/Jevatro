"""Boss 规则引擎单元测试。"""
from rules import (BASE_AND_INC, boss_rules, effective_hand_levels,
                   is_debuffed, legal_hand_types)


def blind(name, btype="BOSS"):
    return {"blinds": {"boss": {"name": name, "type": btype, "status": "CURRENT", "score": 600}}}


def C(suit, rank):
    return {"key": f"{suit}_{rank}", "value": {"suit": suit, "rank": rank},
            "modifier": [], "state": []}


# --- The Psychic：必须出 5 张 ---
r = boss_rules(blind("The Psychic"))
assert r["exact_play"] == 5 and r["is_boss"]
assert boss_rules(blind("Small Blind", "SMALL"))["exact_play"] is None
print("OK psychic exact_play=5")

# --- 花色 Boss 弱化 ---
r = boss_rules(blind("The Window"))  # 方块弱化
assert is_debuffed(C("D", "7"), r) and not is_debuffed(C("H", "7"), r)
assert is_debuffed({"value": {"suit": "S", "rank": "2"}, "state": ["debuff"], "modifier": []},
                   boss_rules(blind("Small Blind", "SMALL")))
print("OK debuff suits + state flags")

# --- The Eye / The Mouth 牌型限制 ---
gs_eye = blind("The Eye")
gs_eye["hands"] = {"Pair": {"played_this_round": 1, "played": 3, "level": 1, "chips": 10, "mult": 2},
                   "Flush": {"played_this_round": 0, "played": 1, "level": 1, "chips": 35, "mult": 4}}
only, banned = legal_hand_types(gs_eye, boss_rules(gs_eye))
assert banned == {"Pair"} and only is None

gs_mouth = blind("The Mouth")
gs_mouth["hands"] = dict(gs_eye["hands"])
only, banned = legal_hand_types(gs_mouth, boss_rules(gs_mouth))
assert only == {"Pair"} and not banned
print("OK eye/mouth type limits")

# --- The Arm / The Flint 等级修正 ---
gs_arm = blind("The Arm")
gs_arm["hands"] = {"Flush": {"played": 0, "played_this_round": 0, "level": 3, "chips": 65, "mult": 8}}
eff = effective_hand_levels(gs_arm, boss_rules(gs_arm))
bc, bm, ic, im = BASE_AND_INC["Flush"]
# 原等级3=bc+2*inc(=65)，The Arm 降为等级2 → bc+1*inc
assert gs_arm["hands"]["Flush"]["chips"] == bc + 2 * ic
assert eff["Flush"]["chips"] == bc + 1 * ic and eff["Flush"]["mult"] == bm + 1 * im

gs_flint = blind("The Flint")
gs_flint["hands"] = {"Pair": {"level": 2, "chips": 25, "mult": 3, "played": 0, "played_this_round": 0}}
eff = effective_hand_levels(gs_flint, boss_rules(gs_flint))
assert eff["Pair"]["chips"] == 12 and eff["Pair"]["mult"] == 1
print("OK arm/flint level adjustments")

print("ALL PASS")
