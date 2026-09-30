"""扫种子：找"我们的动作序列下"商店真实可买 Baron/Mime/Blueprint 的种子。

背景：社区种子的货架描述依赖发现者的动作序列（跳盲/购买消耗随机流），
与 bot 路径不同必然分叉——所以要用自己的动作序列扫。

用法: python scan_baron.py [起始编号] [数量] [牌组]
输出: 命中种子列表（shop1/shop2 的钢K引擎件）
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ENGINE = {"j_baron": "男爵", "j_mime": "哑剧", "j_blueprint": "蓝图",
          "j_brainstorm": "头脑风暴", "j_burnt": "烧焦", "j_dna": "DNA"}


def call(method, **params):
    req = urllib.request.Request(
        "http://127.0.0.1:12346/",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                         "params": params}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read()).get("result", {})


def shop_engine_parts(gs: dict) -> list[str]:
    parts = []
    for area in ("shop", "packs", "vouchers"):
        for c in (gs.get(area) or {}).get("cards", []):
            if c.get("key") in ENGINE:
                parts.append(c["key"])
    return parts


def reach_shop2(seed: str, deck: str) -> tuple[dict | None, list[str]]:
    """推进两个商店（debug set 跳过战斗），收集引擎件命中。"""
    hits: list[str] = []
    gs = call("start", deck=deck, stake="WHITE", seed=seed)
    if gs.get("state") == "MENU":
        return None, []
    for shop_no in range(2):
        for _ in range(80):
            st = gs.get("state")
            if st == "SHOP":
                hits += shop_engine_parts(gs)
                gs = call("next_round")
                break
            if st == "GAME_OVER":
                return gs, hits
            if st == "BLIND_SELECT":
                gs = call("select")
            elif st == "SELECTING_HAND":
                need = 300
                for b in (gs.get("blinds") or {}).values():
                    if isinstance(b, dict) and b.get("status") in ("CURRENT", "SELECT"):
                        need = b.get("score", 300)
                gs = call("set", chips=max(need, 1))
                gs = call("play", cards=[0, 1, 2, 3, 4])
            elif st == "ROUND_EVAL":
                gs = call("cash_out")
            else:
                gs = call("gamestate")
            time.sleep(0.25)
    return gs, hits


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    deck = sys.argv[3] if len(sys.argv) > 3 else "RED"
    call("menu")
    time.sleep(2)
    found = {}
    for i in range(start, start + count):
        seed = f"BARONSCAN{i}"
        gs = call("menu")
        time.sleep(1.5)
        _, hits = reach_shop2(seed, deck)
        names = [ENGINE[h] for h in hits]
        if hits:
            found[seed] = names
            print(f"★ {seed}: {'、'.join(names)}")
        else:
            print(f"  {seed}: 无")
        call("menu")
        time.sleep(1)
    print()
    print("== 命中汇总 ==")
    for s, ns in found.items():
        print(f"  {s}: {ns}")
    best = max(found.items(), key=lambda kv: len(kv[1]), default=None)
    if best:
        print(f"\n推荐种子: {best[0]} ({'、'.join(best[1])})")


if __name__ == "__main__":
    main()
