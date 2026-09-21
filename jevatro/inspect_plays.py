"""Boss 盲下的出牌合法性查证：找出盲注名与每次 play 的卡数/结果。"""
import glob
import io
import json
import sys

f = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("logs/run_jev_*.jsonl"))[-1]
recs = [json.loads(l) for l in io.open(f, encoding="utf-8")]
cur_boss = None
for r in recs:
    if r["kind"] != "action":
        continue
    if r["method"] == "select":
        pass
    if r["method"] == "play":
        n = len(r["params"]["cards"])
        ante, rd = r["before"]["ante"], r["before"]["round"]
        print(f"ante{ante} r{rd} play {r['params']['cards']} ({n}张) "
              f"chips {r['before']['chips']}->{r['after']['chips']} "
              f"hands {r['before']['hands_left']}->{r['after']['hands_left']} "
              f"{'ERR:' + r['error'][:60] if r.get('error') else 'OK'}")
