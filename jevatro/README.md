# Jevatro — 小丑牌 × Jev 决策引擎

依据《小丑牌×Jev 结合技术方案》实施。当前进度：**M2 Jev 决策层已上线（商店/盲注由 Jev 驱动）**。

## 目录结构

```
jevatro/
├── client.py        # BalatroBot JSON-RPC 2.0 客户端（127.0.0.1:12346）
├── scoring.py       # 算分核：牌型识别 + chips/mult + 常见静态小丑效果表
├── solver.py        # 出牌求解器：枚举 ≤5 张全部组合取最优（Tier 0）
├── serializer.py    # gamestate → Jev 紧凑中文 state（含 266 张卡释义）
├── card_desc.py     # 自动生成：卡牌 key → 效果描述（150小丑/52消耗/32券/32包）
├── build_card_desc.py # 释义库生成脚本（从 balatrobot 文档提取）
├── jev_layer.py     # Tier 1：商店 Composite Scoring + 盲注 Noul + 方向 fan-out
├── jev_bot.py       # Jev 驱动 bot（求解器出牌 + Jev 商店/盲注 + Planet 即用）
├── naive_bot.py     # 基线 bot（配置 A/B）
├── logger.py        # JSONL 逐决策日志（含 Jev 问答全量记录）
├── dashboard.py     # 本地 Web 决策面板 → http://127.0.0.1:8765
├── analyze_run.py   # 日志分析 / inspect_jev.py Jev 打分明细
├── test_scoring.py  # 算分核单元测试
└── logs/            # 运行日志
```

## 环境（已部署）

| 组件 | 版本 | 位置 |
|---|---|---|
| Balatro | Steam 正版 | `D:\software\Steam\steamapps\common\Balatro` |
| Lovely 注入器 | v0.9.0 | 游戏目录 `version.dll` |
| Steamodded | 26.829.0 | `%AppData%\Balatro\Mods\Steamodded` |
| balatrobot | v1.5.2 | `%AppData%\Balatro\Mods\balatrobot`（API 端口 12346） |

依赖：`pip install requests`（Python 3.10+）。

## 使用

```bash
# 1. 启动游戏（带 mod，自动监听 12346）
start "" "D:\software\Steam\steamapps\common\Balatro\Balatro.exe"

# 2. 跑一局
cd jevatro
python naive_bot.py JEVATRO1        # 基线（solver + 朴素商店）
python jev_bot.py   JEVATRO1        # Jev 驱动（需 .env 里的 TYPESAFE_API_KEY）

# 3. Web 决策面板（另开终端）
python dashboard.py                 # → http://127.0.0.1:8765
python analyze_run.py               # 最新日志分析
python inspect_jev.py               # Jev 每题打分/置信度明细
```

## 同种子 A/B 实测（JEVATRO1 · 红牌组 · 白注）

| 配置 | 结果 | 商店行为 | 单手最高分 |
|---|---|---|---|
| naive | Ante 2 r4 阵亡 | 买 2 小丑（见啥买啥） | 316 |
| jev v1（门槛过严） | Ante 1 r3 阵亡 | **零购买**（conf 门误杀） | 316 |
| **jev v3（调参后）** | **Ante 2 r5 阵亡** | 4 次购买含 Saturn→顺子升级、首次自主跳盲 | **2071** |

关键证据：j_misprint 买入后单手 Flush 从 284 → 1136；Saturn 买入即用后 Straight 2071。

## 决策架构现状

| 决策点 | 承担者 | 状态 |
|---|---|---|
| 出牌/弃牌 | Tier 0 求解器（全枚举精确） | ✅ |
| 商店买什么/买不买 | Tier 1 Jev Composite Scoring（4维rubric+方向权重） | ✅ |
| 跳不跳盲 | Tier 0 can_clear + Tier 1 Noul 兜底 | ✅ |
| Planet 使用 | 买入即用 | ✅ |
| Tarot / 卡包 / 弃牌方向 / 卖小丑 | 未实现（第三轮迭代） | ⬜ |

## 已知问题
- balatrobot v1.5.2 上游 bug：`menu()` 后 `start` 崩溃（viewed_back nil）——已给本地 mod 打补丁；
- Jev 置信度实测多为 0~0.4，"0.0"含义接近"无信号"而非"不可靠"，当前只记录不门控；
- econ 方向在 fan-out 里偏热（钱少时也触发），靠 50/50 default 混合抑制；
- 小丑效果表覆盖 ~45 张静态卡，动态成长型按 0 计（低估但不非法）。
