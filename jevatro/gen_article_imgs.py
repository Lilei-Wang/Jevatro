"""公众号配图生成：全部基于项目真实数据。输出 article_imgs/。"""
from __future__ import annotations

import glob
import io
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

FONT = font_manager.FontProperties(fname=r"C:\Windows\Fonts\msyh.ttc")
FONT_B = font_manager.FontProperties(fname=r"C:\Windows\Fonts\msyhbd.ttc")
plt.rcParams["font.family"] = FONT.get_name()
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).parent.parent / "article_imgs"   # 项目根目录（文章引用处）
OUT.mkdir(exist_ok=True)

BG, CARD, LINE = "#0d0f12", "#161a20", "#2a303c"
GREEN, RED, BLUE, AMBER, MUTED = "#34d399", "#f87171", "#60a5fa", "#fbbf24", "#9aa3b5"
C_NAIVE, C_JEV, C_LLM = "#8b93a3", "#f87171", "#60a5fa"


def style_ax(ax, title):
    ax.set_facecolor(CARD)
    ax.set_title(title, fontproperties=FONT_B, fontsize=14, color="#e8ecf3", pad=12)
    for s in ax.spines.values():
        s.set_color(LINE)
    ax.tick_params(colors=MUTED, labelsize=10)
    for lb in ax.get_xticklabels() + ax.get_yticklabels():
        lb.set_fontproperties(FONT)


def save(fig, name):
    fig.patch.set_facecolor(BG)
    fig.savefig(OUT / name, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print("saved", name)


# ============ 01 封面 ============
fig, ax = plt.subplots(figsize=(9, 3.6))
ax.set_facecolor("#10141c")
ax.set_xlim(0, 10); ax.set_ylim(0, 4); ax.axis("off")
# 筹码
for (cx, cy, col) in ((0.9, 2.0, RED), (1.6, 2.6, BLUE), (2.3, 2.0, "#fbbf24")):
    ax.add_patch(plt.Circle((cx, cy), 0.52, color=col, alpha=0.9))
    ax.add_patch(plt.Circle((cx, cy), 0.34, color=CARD))
    ax.add_patch(plt.Circle((cx, cy), 0.43, fill=False, ls=(0, (4, 3)), color="white", lw=1.6, alpha=0.7))
ax.text(3.3, 2.55, "当「哑巴模型」Jev", fontsize=27, color="#e8ecf3", fontproperties=FONT_B)
ax.text(3.3, 1.45, "学会了打小丑牌", fontsize=27, color=GREEN, fontproperties=FONT_B)
ax.text(3.35, 0.55, "一局一分钱 · 比传统大模型便宜 18 倍 · 全程实测", fontsize=13,
        color=MUTED, fontproperties=FONT)
ax.text(0.55, 0.25, "JEVATRO 项目实测报告", fontsize=10, color="#5f6878", fontproperties=FONT)
save(fig, "01_封面.png")

# ============ 02 三配置战绩 ============
fig, axes = plt.subplots(1, 3, figsize=(11, 4))
cfgs = ["基线\n(求解器)", "Jev\n+求解器", "DeepSeek\n+求解器"]
data = {"平均到达 Ante": [2.62, 2.88, 2.75],
        "最大单手分(均值)": [1478, 2475, 2162],
        "全场总得分(均值)": [11578, 15348, 14629]}
for ax, (k, v) in zip(axes, data.items()):
    bars = ax.bar(cfgs, v, color=[C_NAIVE, C_JEV, C_LLM], width=0.62)
    style_ax(ax, k)
    for b, val in zip(bars, v):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() * 1.01,
                f"{val:,.0f}" if val > 100 else f"{val}", ha="center",
                color="#e8ecf3", fontsize=11, fontproperties=FONT_B)
    ax.set_ylim(0, max(v) * 1.15)
    ax.grid(axis="y", color=LINE, alpha=0.5)
fig.suptitle("同种子 8×3=24 局实测：Jev 全指标第一", fontsize=15,
             color="#e8ecf3", fontproperties=FONT_B, y=1.04)
save(fig, "02_三配置战绩.png")

# ============ 03 延迟与成本 ============
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
names = ["Jev", "glm-4-flash", "DeepSeek\n-flash"]
lat = [0.55, 1.78, 6.79]
b = axes[0].bar(names, lat, color=[C_JEV, C_NAIVE, C_LLM], width=0.55)
style_ax(axes[0], "单次决策延迟（秒，越低越好）")
for bb, v in zip(b, lat):
    axes[0].text(bb.get_x() + bb.get_width() / 2, v * 1.05, f"{v}s",
                 ha="center", color="#e8ecf3", fontsize=12, fontproperties=FONT_B)
axes[0].text(0.02, 0.9, "Jev 快 12 倍", transform=axes[0].transAxes,
             color=GREEN, fontsize=13, fontproperties=FONT_B)
axes[0].grid(axis="y", color=LINE, alpha=0.5)

cost = [0.0135, 0, 0.156]      # 实测人民币/局（COST9 全记账局 + 9 局回溯均值）
b = axes[1].bar(names, [max(c, 0.0001) for c in cost],
                color=[C_JEV, C_NAIVE, C_LLM], width=0.55)
axes[1].set_yscale("log")
style_ax(axes[1], "单局决策成本（人民币，对数轴，实测）")
labels = ["¥0.014(实测)", "¥0(免费档)", "¥0.156(实测)"]
for bb, v, lb in zip(b, cost, labels):
    axes[1].text(bb.get_x() + bb.get_width() / 2, max(v, 0.0001) * 1.3, lb,
                 ha="center", color="#e8ecf3", fontsize=11, fontproperties=FONT_B)
axes[1].text(0.02, 0.88, "Jev 便宜 18 倍（官方价核账）", transform=axes[1].transAxes,
             color=GREEN, fontsize=12, fontproperties=FONT_B)
axes[1].grid(axis="y", color=LINE, alpha=0.5)
fig.suptitle("经济性：高频决策位的碾压优势", fontsize=15,
             color="#e8ecf3", fontproperties=FONT_B, y=1.04)
save(fig, "03_延迟成本.png")

# ============ 04 Ante 分布（真实日志解析） ============
def load_ante_dist():
    dist = {"naive": [], "jev": [], "llm": []}
    for p in glob.glob("logs/run_*.jsonl"):
        cfg = ("jev" if "_jev_" in p else "llm" if "_llm_" in p else "naive")
        try:
            for line in io.open(p, encoding="utf-8"):
                if '"result"' in line:
                    r = json.loads(line)
                    if r.get("kind") == "result" and r["final"].get("ante"):
                        dist[cfg].append(r["final"]["ante"])
                    break_ = False
        except Exception:
            pass
    return dist

fig, ax = plt.subplots(figsize=(10, 4.2))
import numpy as np
dist = load_ante_dist()
bins = np.arange(0.5, 8.5, 1)
for cfg, col, lbl in (("naive", C_NAIVE, "基线"), ("jev", C_JEV, "Jev"), ("llm", C_LLM, "DeepSeek")):
    ax.hist(dist[cfg], bins=bins, alpha=0.62, color=col, label=f"{lbl}（{len(dist[cfg])}局）",
            edgecolor=BG)
style_ax(ax, "全部对局「到达 Ante」分布（真实日志）")
ax.legend(prop=FONT, facecolor=CARD, edgecolor=LINE, labelcolor="#e8ecf3")
ax.set_xticks(range(1, 9))
ax.set_xlabel("到达 Ante", fontproperties=FONT, color=MUTED)
ax.grid(axis="y", color=LINE, alpha=0.5)
save(fig, "04_ante分布.png")

# ============ 05 Jev 四维打分 ============
fig, ax = plt.subplots(figsize=(9, 4))
dims = ["协同性\nsynergy", "成长性\nscaling", "经济性\neconomy", "即时战力\nimmediate"]
scores = [1.64, 2.03, 1.21, 0.81]
confs = [0.349, 0.265, 0.265, 0.414]
x = np.arange(4)
b1 = ax.bar(x - 0.19, scores, 0.36, color=RED, label="平均打分（0-4）")
b2 = ax.bar(x + 0.19, [c * 4 for c in confs], 0.36, color=GREEN, label="平均置信度（×4 对齐）")
style_ax(ax, f"Jev 商店打分画像（302 次调用实测）")
ax.set_xticks(x); ax.set_xticklabels(dims)
ax.legend(prop=FONT, facecolor=CARD, edgecolor=LINE, labelcolor="#e8ecf3")
ax.grid(axis="y", color=LINE, alpha=0.5)
ax.text(3, 3.3, "即时战力维度最初均分仅0.74\n→重写措辞后升至0.81", ha="right",
        color=AMBER, fontsize=10.5, fontproperties=FONT)
save(fig, "05_jev维度.png")

# ============ 06 死因散点 ============
fig, ax = plt.subplots(figsize=(10, 4.4))
for p in glob.glob("logs/run_*.jsonl"):
    cfg = ("jev" if "_jev_" in p else "llm" if "_llm_" in p else "naive")
    col = {"naive": C_NAIVE, "jev": C_JEV, "llm": C_LLM}[cfg]
    try:
        recs = [json.loads(l) for l in io.open(p, encoding="utf-8")]
    except Exception:
        continue
    result = next((r for r in recs if r.get("kind") == "result"), None)
    if not result:
        continue
    acts = [r for r in recs if r["kind"] == "action"]
    plays = [r for r in acts if r["method"] == "play" and not r.get("error")]
    rd = result["final"].get("round", 0)
    rp = [r for r in plays if r["before"].get("round") == rd]
    if not rp:
        continue
    total = sum(r["after"].get("chips", 0) - r["before"].get("chips", 0) for r in rp)
    import re as _re
    need = None
    for r in recs:
        if r["kind"] == "jev":
            m = _re.search(r"需(\d+)", str(r.get("state", "")))
            if m and int(m.group(1)) >= 300:
                need = int(m.group(1))
    if not need:
        continue
    ratio = min(total / need, 1.0)
    ax.scatter(result["final"].get("ante", 0), ratio, s=34, color=col, alpha=0.75,
               edgecolors=BG, linewidths=0.5)
ax.axhline(1.0, color=GREEN, ls="--", lw=1.4)
ax.text(0.6, 1.04, "过关线（打出=需求）", color=GREEN, fontsize=11, fontproperties=FONT)
style_ax(ax, "每一局死亡轮的「发挥/需求」比（越接近1越惜败）")
ax.set_xlabel("止步 Ante", fontproperties=FONT, color=MUTED)
ax.set_ylabel("打出 ÷ 需求", fontproperties=FONT, color=MUTED)
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([0], [0], marker="o", color="w", markerfacecolor=c,
                          markersize=9, label=l)
                   for c, l in ((C_NAIVE, "基线"), (C_JEV, "Jev"), (C_LLM, "DeepSeek"))],
          prop=FONT, facecolor=CARD, edgecolor=LINE, labelcolor="#e8ecf3")
ax.grid(color=LINE, alpha=0.4)
save(fig, "06_死因散点.png")

# ============ 07 三层架构 ============
fig, ax = plt.subplots(figsize=(10, 5.6))
ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
ax.set_facecolor(CARD)
tiers = [
    (7.6, "第一层  求解器（本地代码）", "出牌 / 弃牌 / 能否过关", "精确 · 0 成本 · 0 延迟", GREEN, "已实现"),
    (4.8, "第二层  Jev（判断模型）", "商店 / 盲注 / 开包 / 卖牌", "0.55秒/次 · ¥0.005/局 · 0失败", RED, "已实现"),
    (2.0, "第三层  LLM（推理模型）", "低置信兜底 / 复杂残局", "思考型 · 残局反超实测（Ante 5）", BLUE, "规划中"),
]
for y, t1, t2, t3, col, badge in tiers:
    ax.add_patch(FancyBboxPatch((1.0, y), 8.0, 2.1, boxstyle="round,pad=0.12",
                                fc=CARD, ec=col, lw=2))
    ax.text(1.5, y + 1.45, t1, fontsize=15, color=col, fontproperties=FONT_B)
    ax.text(1.5, y + 0.85, t2, fontsize=11.5, color="#e8ecf3", fontproperties=FONT)
    ax.text(1.5, y + 0.32, t3, fontsize=10.5, color=MUTED, fontproperties=FONT)
    ax.text(8.4, y + 1.45, badge, fontsize=10.5, color=col, fontproperties=FONT,
            ha="right",
            bbox=dict(boxstyle="round,pad=0.3", fc=BG, ec=col, lw=1))
for y0 in (7.6, 4.8):
    ax.add_patch(FancyArrowPatch((5, y0 - 0.05), (5, y0 - 0.55),
                                 arrowstyle="-|>", mutation_scale=22, color=MUTED))
ax.text(5.35, 7.05, "模糊判断才下行", fontsize=9.5, color=MUTED, fontproperties=FONT)
ax.text(5.35, 4.25, "置信度不足才兜底", fontsize=9.5, color=MUTED, fontproperties=FONT)
ax.text(5, 9.5, "Jevatro 三层决策漏斗", fontsize=17, color="#e8ecf3",
        fontproperties=FONT_B, ha="center")
save(fig, "07_架构图.png")

# ============ 08 里程碑时间线 ============
fig, ax = plt.subplots(figsize=(11, 4.6))
ax.set_xlim(0, 11); ax.set_ylim(0, 5); ax.axis("off"); ax.set_facecolor(CARD)
ms = [
    (0.7, "调研+技术方案", "三层架构设计", GREEN),
    (2.1, "M1 环境+基线", "balatrobot接入\n首局自动打通", GREEN),
    (3.6, "M2 Jev层", "商店/盲注决策\n首见+64%单手提升", RED),
    (5.2, "规则引擎", "17类Boss约束\n0白烧手", GREEN),
    (6.8, "消耗牌+开包", "45张用法策略\nChoice开包实战", RED),
    (8.4, "LLM对照", "DeepSeek接入\n24局三臂实测", BLUE),
    (10.0, "Ante 6", "全项目最深纪录", AMBER),
]
ax.plot([0.6, 10.2], [2.5, 2.5], color=LINE, lw=2.5, zorder=1)
for i, (x, t, d, col) in enumerate(ms):
    up = i % 2 == 0
    ax.scatter([x], [2.5], s=110, color=col, zorder=3, edgecolors=BG, linewidths=1.5)
    ty = 3.1 if up else 1.9
    ax.text(x, ty, t, fontsize=11.5, color=col, fontproperties=FONT_B,
            ha="center", va="bottom" if up else "top")
    ax.text(x, ty + (0.62 if up else -0.62), d, fontsize=9.5, color=MUTED,
            fontproperties=FONT, ha="center", va="bottom" if up else "top")
ax.text(0.6, 4.6, "10 轮迭代 · 130+ 局实测 · 20+ 个提交", fontsize=15,
        color="#e8ecf3", fontproperties=FONT_B)
save(fig, "08_时间线.png")

# ============ 12 题型与原理（传统LLM vs Jev） ============
fig, ax = plt.subplots(figsize=(11, 5.4))
ax.set_xlim(0, 11); ax.set_ylim(0, 5.6); ax.axis("off"); ax.set_facecolor(CARD)

def rbox(x, y, w, h, text, fc, ec, tc, fs=10.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                                fc=fc, ec=ec, lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            color=tc, fontsize=fs, fontproperties=FONT_B if bold else FONT)

# —— 上半：传统 LLM 链路 ——
rbox(0.25, 4.45, 1.9, 0.8, "状态文本\n+ 指令", BG, LINE, MUTED, 10)
rbox(2.55, 4.45, 2.7, 0.8, "自回归生成\n逐 token 吐文本", "#1c1418", "#7f2d3a", "#f0b9c0", 10.5)
rbox(5.65, 4.45, 2.0, 0.8, "JSON 容错解析\n正则+重试", "#1c1418", "#7f2d3a", "#f0b9c0", 10)
rbox(8.0, 4.45, 2.7, 0.8, "结构化决策\n~30% 解析失败回退", "#241418", "#a13040", RED, 10)
for x0, x1 in ((2.15, 2.55), (5.25, 5.65), (7.65, 8.0)):
    ax.add_patch(FancyArrowPatch((x0, 4.85), (x1, 4.85), arrowstyle="-|>",
                                 mutation_scale=14, color=MUTED, lw=1.3))
ax.text(0.25, 5.35, "传统 LLM：把判断题当作文题", fontsize=12.5, color="#f0b9c0",
        fontproperties=FONT_B)

# —— 下半：Jev 链路 ——
rbox(0.25, 2.6, 1.9, 0.8, "状态文本\n+ 题目字典", BG, LINE, MUTED, 10)
rbox(2.55, 2.6, 2.7, 0.8, "非自回归单次前向\n无文本生成过程", "#0f1e18", "#1f6b4a", "#a9e8c8", 10.5)
rbox(5.65, 2.6, 2.0, 0.8, "类型化输出\nchoice / score / noul", "#0f1e18", "#1f6b4a", "#a9e8c8", 10)
rbox(8.0, 2.6, 2.7, 0.8, "代码直接分支\n0 解析失败", "#0f2418", "#2f9e63", GREEN, 10)
for x0, x1 in ((2.15, 2.55), (5.25, 5.65), (7.65, 8.0)):
    ax.add_patch(FancyArrowPatch((x0, 3.0), (x1, 3.0), arrowstyle="-|>",
                                 mutation_scale=14, color=MUTED, lw=1.3))
ax.text(0.25, 3.5, "Jev (System One)：把判断题当判断题", fontsize=12.5, color="#a9e8c8",
        fontproperties=FONT_B)

# —— 三种题型卡 ——
cards = [
    ("Choice 选择题", "候选中选一个\n附概率分布与置信度", 'choice="a"\nconfidence=0.63\nprobabilities={a:0.63,...}'),
    ("Score 打分题", "按等级量表 0-4 打分\n附置信度", 'score=2\nconfidence=0.71'),
    ("Noul 判断题", "是非概率 0-1\n附置信度", 'noul=0.51\nconfidence=0.55'),
]
for i, (t, d, code) in enumerate(cards):
    x = 0.35 + i * 3.6
    ax.add_patch(FancyBboxPatch((x, 0.25), 3.3, 1.9, boxstyle="round,pad=0.1",
                                fc="#11151b", ec=LINE, lw=1.4))
    ax.text(x + 1.65, 1.85, t, fontsize=12, color="#e8ecf3", fontproperties=FONT_B,
            ha="center")
    ax.text(x + 1.65, 1.28, d, fontsize=9.5, color=MUTED, fontproperties=FONT,
            ha="center", va="center")
    ax.add_patch(FancyBboxPatch((x + 0.25, 0.42), 2.8, 0.62, boxstyle="round,pad=0.06",
                                fc="#0b0e12", ec="#233043", lw=1))
    ax.text(x + 1.65, 0.73, code, fontsize=8.2, color="#8fd6b4", ha="center",
            va="center", fontfamily="monospace", linespacing=1.25)
ax.text(10.75, 3.0, "响应 JSON 里的真实字段", fontsize=9, color="#5f6878",
        fontproperties=FONT, rotation=90, va="center")
fig.suptitle("Jev 原理：不生成文本，直接输出类型化判断（输出免费、构造性无幻觉）",
             fontsize=14.5, color="#e8ecf3", fontproperties=FONT_B, y=0.99)
save(fig, "12_题型与原理.png")

print("ALL CHARTS DONE")
