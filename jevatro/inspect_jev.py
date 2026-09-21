"""查看 jev 调用详情：各商品四维得分/置信度/综合值。"""
import glob
import io
import json
import sys

f = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("logs/run_jev_*.jsonl"))[-1]
print("==", f)
for line in io.open(f, encoding="utf-8"):
    r = json.loads(line)
    if r["kind"] == "jev":
        print(f"\n--- t={r['t']}s latency={r['latency']}s ---")
        print("STATE:")
        print(r["state"][:900])
        print("ANSWERS:")
        for k, a in r["answers"].items():
            if k.startswith("arch_"):
                print(f"  {k:14s} noul={a.get('noul')}")
            elif "__" in k:
                print(f"  {k:22s} score={a.get('score')} conf={a.get('confidence')}")
            else:
                print(f"  {k:14s} {a}")
    elif r["kind"] == "action" and r["method"] in ("buy", "reroll"):
        print(f"  >> BUY/REROLL {r['params']} why={r.get('extra',{}).get('why')} err={r.get('error')}")
    elif r["kind"] == "jev_error":
        print("  >> JEV_ERROR", r["error"])
