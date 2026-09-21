"""从 balatrobot docs/api.md 的卡牌表格提取 key→效果描述 字典，生成 card_desc.py。"""
import re
from pathlib import Path

SRC = Path(r"D:\AI项目\小丑牌\_downloads\balatrobot-1.5.2\docs\api.md")
OUT = Path(__file__).parent / "card_desc.py"

text = SRC.read_text(encoding="utf-8")
desc: dict[str, str] = {}
pat = re.compile(r"^\|\s*`?([jcvp]_[a-z0-9_]+)`?\s*\|\s*(.+?)\s*\|\s*$", re.M)
for key, effect in pat.findall(text):
    if key not in desc:  # 表格先到先得
        desc[key] = re.sub(r"\s+", " ", effect)

print("extracted:", len(desc), "cards")
print("j_*:", sum(1 for k in desc if k.startswith("j_")))
print("c_*:", sum(1 for k in desc if k.startswith("c_")))
print("v_*:", sum(1 for k in desc if k.startswith("v_")))
print("p_*:", sum(1 for k in desc if k.startswith("p_")))

with OUT.open("w", encoding="utf-8") as f:
    f.write('"""自动生成：卡牌 key → 效果描述（来自 balatrobot docs/api.md）。"""\n')
    f.write("CARD_DESC = {\n")
    for k in sorted(desc):
        f.write(f"    {k!r}: {desc[k]!r},\n")
    f.write("}\n")
print("written:", OUT)
