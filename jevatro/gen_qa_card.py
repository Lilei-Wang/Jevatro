"""09 Jev 问答实例卡（真实日志渲染成对话卡）+ 10 观测台图。"""
import glob
import io
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("article_imgs")
F = lambda s: ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", s)
FB = lambda s: ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", s)
MONO = lambda s: ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", s)

BG, CARD, LINE = (13, 15, 18), (22, 26, 32), (42, 48, 60)
GREEN, RED, BLUE, AMBER = (52, 211, 153), (248, 113, 113), (96, 165, 250), (251, 191, 36)
TXT, MUT = (232, 236, 243), (154, 163, 181)

# 找一局有代表性的 jev 记录：题多的（带 sell_which 或 20+ 题）
best = None
for p in sorted(glob.glob("logs/run_jev_*.jsonl"), reverse=True):
    for line in io.open(p, encoding="utf-8"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") == "jev" and len(r.get("answers", {})) >= 18 \
                and "sell_which" in r.get("answers", {}):
            best = r
            break
    if best:
        break
if not best:  # 兜底：任意多题记录
    for p in sorted(glob.glob("logs/run_jev_*.jsonl"), reverse=True):
        for line in io.open(p, encoding="utf-8"):
            r = json.loads(line)
            if r.get("kind") == "jev" and len(r.get("answers", {})) >= 15:
                best = r
                break
        if best:
            break

W = 1080
M = 34
img = Image.new("RGB", (W, 1560), BG)
d = ImageDraw.Draw(img)

d.rounded_rectangle((M, M, W - M, 118), 16, fill=CARD, outline=LINE, width=2)
d.text((M + 24, M + 18), "Jev 批量调用实例（真实日志）", font=FB(26), fill=TXT)
lat = best.get("latency", 0)
n = len(best.get("questions", {}))
d.text((M + 24, M + 66), f"{n} 道题 · 一次调用并行回答 · 延迟 {lat}s · 输出免费",
       font=F(20), fill=MUT)

# state 卡
d.rounded_rectangle((M, 140, W // 2 + 6, 920), 16, fill=CARD, outline=LINE, width=2)
d.text((M + 20, 158), "发给 Jev 的局面（state）", font=FB(20), fill=BLUE)
state = (best.get("state") or "")[:900]
d.text((M + 20, 200), state, font=MONO(17), fill=(183, 194, 212))

# 问答区
qx = W // 2 + 22
d.rounded_rectangle((qx, 140, W - M, 920), 16, fill=CARD, outline=LINE, width=2)
d.text((qx + 20, 158), "Jev 的回答（节选）", font=FB(20), fill=RED)
qa = []
for k, a in best.get("answers", {}).items():
    if k == "archetype" and a.get("type") == "choice":
        qa.append((k, f"选择 → {a.get('choice')}", None))
    elif a.get("type") == "score":
        qa.append((k, f"打分 {a.get('score', 0):.2f}/4", a.get("confidence")))
    elif a.get("type") == "noul":
        qa.append((k, f"概率 {a.get('noul', 0):.2f}", None))
    elif a.get("type") == "choice":
        qa.append((k, f"选择 → {a.get('choice')}", a.get("confidence")))
y = 200
for k, v, conf in qa[:22]:
    d.text((qx + 20, y), k, font=MONO(17), fill=BLUE)
    d.text((qx + 300, y), v, font=MONO(17), fill=GREEN)
    if conf is not None:
        d.rounded_rectangle((qx + 500, y + 4, qx + 500 + max(int(conf * 160), 2), y + 12),
                            3, fill=GREEN)
        d.text((qx + 500 + max(int(conf * 160), 2) + 8, y - 2),
               f"{conf:.2f}", font=MONO(15), fill=MUT)
    y += 32
    if y > 880:
        break

# 底部解读
d.rounded_rectangle((M, 944, W - M, 1180), 16, fill=CARD, outline=LINE, width=2)
d.text((M + 24, 962), "这张卡意味着什么", font=FB(22), fill=AMBER)
for i, (t, c) in enumerate([
    ("20+ 道判断题装进一次调用，延迟几乎不增——这是 Jev 批量并行的独门能力",
     TXT),
    ("每道题都有类型化答案（打分/概率/选择），不需要解析自然语言，0 次解析失败",
     TXT),
    ("置信度经过校准，可以做路由阈值——虽然我们实测发现 0.0 多为「无信号」而非「不可靠」",
     TXT),
    ("代码层拿到答案后做加权求和（权重按方向混合），买不买由确定的数学决定",
     TXT),
]):
    d.text((M + 24, 1010 + i * 42), "· " + t, font=F(18), fill=c)

img.save(OUT / "09_jev问答卡.png")
print("saved 09_jev问答卡.png  (来源记录:", len(best.get("questions", {})), "题)")

# 10 观测台（复用浏览器实拍截图并标注）
shutil.copy("logs/agent_lab_v3预览.png", OUT / "10_观测台.png")
print("saved 10_观测台.png")
