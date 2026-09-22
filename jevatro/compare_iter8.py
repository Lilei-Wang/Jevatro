"""对比迭代8前后 jev 局的关键指标（文件时间戳 21:05 后为新版）。"""
import glob
import io
import json
from pathlib import Path

new, old = [], []
for p in glob.glob("logs/run_jev_20260922_2*.jsonl"):
    ts = Path(p).name.split("_")[-1].replace(".jsonl", "")
    (new if ts >= "210527" else old).append(p)


def stats(files, label):
    rows = []
    for p in files:
        recs = [json.loads(l) for l in io.open(p, encoding="utf-8")
                if l.strip()]
        result = next((r for r in recs if r.get("kind") == "result"), None)
        if not result:
            continue
        f = result["final"]
        buys = sum(1 for r in recs if r.get("kind") == "action"
                   and r["method"] == "buy" and not r.get("error"))
        rows.append({"ante": f.get("ante"), "money": f.get("money"),
                     "n_jokers": f.get("n_jokers"), "buys": buys})
    if not rows:
        print(label, "无数据")
        return
    n = len(rows)
    print(f"{label}: {n}局 平均ante={sum(r['ante'] for r in rows)/n:.2f} "
          f"死时金币=${sum(r['money'] or 0 for r in rows)/n:.0f} "
          f"小丑={sum(r['n_jokers'] or 0 for r in rows)/n:.1f} "
          f"购买={sum(r['buys'] for r in rows)/n:.1f}")


stats(old, "旧版(迭代7前)")
stats(new, "新版(迭代8后)")
