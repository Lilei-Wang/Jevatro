"""分析一局 JSONL 日志。用法: python analyze_run.py [日志文件]"""
import glob
import io
import json
import sys

logs = sorted(glob.glob("logs/run_naive_*.jsonl"))
f = sys.argv[1] if len(sys.argv) > 1 else logs[-1]
lines = [json.loads(l) for l in io.open(f, encoding="utf-8")]

print("file:", f, "records:", len(lines))
kinds = {k: sum(1 for l in lines if l["kind"] == k) for k in set(l["kind"] for l in lines)}
print("kinds:", kinds)
print()
print("--- 一条 play 动作 ---")
plays = [l for l in lines if l["kind"] == "action" and l["method"] == "play"]
print(json.dumps(plays[0], ensure_ascii=False, indent=1)[:700])
print()
print("--- 商店动作 ---")
for l in lines:
    if l["kind"] == "action" and l["method"] in ("buy", "next_round", "cash_out"):
        print(f'{l["t"]:>7}s {l["method"]:<11} {str(l["params"]):<22} '
              f'money_after={l["after"]["money"]}')
print()
print("--- 结局 ---")
for l in lines:
    if l["kind"] == "result":
        print(json.dumps(l, ensure_ascii=False))
