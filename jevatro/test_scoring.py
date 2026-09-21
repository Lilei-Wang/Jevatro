"""算分核快速自测。"""
from scoring import evaluate_hand, score_play


def C(suit, rank, enh=None, ed=None):
    return {"key": f"{suit}_{rank}", "value": {"suit": suit, "rank": rank},
            "modifier": {"seal": None, "edition": ed, "enhancement": enh,
                         "eternal": False, "perishable": None, "rental": False}}


L1 = {"Pair": {"chips": 10, "mult": 2}, "Flush": {"chips": 35, "mult": 4},
      "High Card": {"chips": 5, "mult": 1}, "Straight": {"chips": 30, "mult": 4},
      "Straight Flush": {"chips": 100, "mult": 8}, "Two Pair": {"chips": 20, "mult": 2},
      "Three of a Kind": {"chips": 30, "mult": 3}, "Four of a Kind": {"chips": 60, "mult": 7}}

CTX = {"money": 4, "discards_left": 3, "deck_remaining": 40, "joker_slots": 5}

tests = [
    ([C("H", "A"), C("H", "K"), C("H", "T"), C("H", "5"), C("H", "4")], "Flush"),
    ([C("S", "Q"), C("S", "J"), C("S", "T"), C("S", "9"), C("S", "8")], "Straight Flush"),
    ([C("S", "K"), C("S", "9"), C("D", "9"), C("H", "6"), C("D", "3")], "Pair"),
    ([C("H", "A"), C("S", "2"), C("D", "3"), C("C", "4"), C("H", "5")], "Straight"),
    ([C("H", "K"), C("D", "K"), C("S", "2"), C("D", "2")], "Two Pair"),
    ([C("C", "7"), C("D", "7"), C("H", "7"), C("S", "4"), C("H", "Q")], "Three of a Kind"),
    ([C("H", "3")], "High Card"),
    ([C("H", "J"), C("D", "J"), C("S", "J"), C("C", "J"), C("H", "2")], "Four of a Kind"),
]
ok = True
for cards, want in tests:
    name, idx = evaluate_hand(cards)
    flag = "OK " if name == want else "FAIL"
    if name != want:
        ok = False
    print(flag, name, "scoring_idx=", idx)

pair9 = [C("S", "K"), C("S", "9"), C("D", "9")]
s = score_play(pair9, [1, 2], "Pair", L1, [], CTX)
print("pair9:", s["total"], "expect 56", "OK" if abs(s["total"] - 56) < 1e-6 else "FAIL")

s2 = score_play(pair9, [1, 2], "Pair", L1, [{"key": "j_joker", "modifier": {}}], CTX)
print("pair9+j_joker:", s2["total"], "expect 168", "OK" if abs(s2["total"] - 168) < 1e-6 else "FAIL")

glass = [C("S", "K"), C("S", "9"), C("D", "9", enh="GLASS")]
s3 = score_play(glass, [1, 2], "Pair", L1, [], CTX)
print("glass pair9:", s3["total"], "expect 112", "OK" if abs(s3["total"] - 112) < 1e-6 else "FAIL")

s4 = score_play([C("S", "9"), C("D", "9")], [0, 1], "Pair", L1,
                [{"key": "j_tribe", "modifier": {}}], CTX)  # tribe: flush X2 -> 对子不触发
print("pair9+tribe(no flush):", s4["total"], "expect 56", "OK" if abs(s4["total"] - 56) < 1e-6 else "FAIL")

print("ALL PASS" if ok else "HAS FAILURES")
