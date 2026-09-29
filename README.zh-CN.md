# Jevatro（小丑牌 × Jev 决策引擎）

**自动打《小丑牌》(Balatro) 的 AI Agent：能精确计算的交给求解器，靠直觉判断的交给 Jev。**

[English](README.md) | [中文](README.zh-CN.md)

![架构图](article_imgs/07_架构图.png)

Jevatro 全自动操控真实的 Balatro 游戏（Steam 正版）：游戏控制层复用开源 [balatrobot](https://github.com/coder/balatrobot) mod（游戏内 JSON-RPC 2.0 服务），决策层采用三层漏斗架构：

| 层级 | 决策者 | 负责的决策 | 成本 | 延迟 |
|---|---|---|---|---|
| **Tier 0** | 本地**穷举求解器** | 出牌/弃牌（≤218 种组合全枚举精确算分）；17 类 Boss 盲约束；消耗牌目标选择 | 免费、离线 | ≈0 |
| **Tier 1** | **[Jev](https://typesafe.ai)**（TypeSafe AI 的 System One 决策模型） | 商店买/卖、跳盲注、卡组方向识别、开包选卡、重掷——全部打包进一次 API 调用 | 输入 $0.042/百万 token，**输出免费** | 每批 ~0.6s |
| **Tier 2** | 可选 **LLM 臂**（任意 OpenAI 兼容后端，如 DeepSeek） | A/B 对比基线；低置信度升级目标 | 实测 $0.046/局 | ~6.8s/次 |

Jev API 失败时自动回退朴素策略，**对局永不中断**。

## 为什么这样分层

小丑牌的决策天然分成两类：

- **可精确计算**——出哪几张牌是个小规模组合搜索，交给 LLM（或 Jev）只会徒增成本和延迟，本地求解器免费拿到最优解；
- **模糊直觉判断**——"这个 Joker 值不值得花 $8 买？""这个盲跳不跳？"这正好是 Jev Choice/Score/Noul 题型的主场：原子化提问、结构化回答、校准置信度、批量执行、输出计价为零。

完整论证见[技术方案](小丑牌xJev技术方案.md)——正是心理学 System 1 / System 2 的划分，也是 Jev"System One 模型"命名的本意。

## 实测战绩（全部实测，白注 · 红牌组）

**三配置同种子成对 A/B**——8 种子 × 3 配置，同游戏速度，逐决策 JSONL 日志：

| 指标（均值/局） | naive | **jev** | llm (glm-4-flash) |
|---|---|---|---|
| 到达 Ante | 2.62 | **2.88** | 1.88 |
| 最大单手分 | 1,478 | **2,475**（+68%） | 979 |
| 全场总得分 | 11,578 | **15,348**（+33%） | 3,738 |
| 购买数/局 | 4.12 | **7.00** | 3.12 |
| 跳盲数/局 | 0 | **0.38** | 1.88 |
| 决策延迟/次 | — | **0.55s** | 1.78s |

![三配置战绩](article_imgs/02_三配置战绩.png)

**Jev vs DeepSeek-flash**（8 种子成对）：

| | **jev** | deepseek-flash |
|---|---|---|
| 平均 Ante | **2.88** | 2.75 |
| 单次决策延迟 | **0.55s** | 6.79s（12 倍） |
| API 失败 | **0 / 149 次** | ~30%（回退启发式） |
| 8 局 token | 0.30M 入 / **0 出** | 43K 入 / 116K 出 |
| 实测单局成本 | **$0.0019** | $0.046（约 24 倍） |

**诚实进度**：目前最深一局 **Ante 6**（通关 = Ante 8），20 种子批量均值 2.85。Jev 层的优势首先体现在得分上限（单手 +68%）、总产出、延迟、成本与零 API 失败上——冲刺最后几个 Ante 是进行中的工作（见[执行日志](EXECUTION_LOG.md)，已完成 13 轮迭代）。

## 决策覆盖

| 决策点 | 承担者 | 状态 |
|---|---|---|
| 出牌 / 弃牌 | Tier 0 求解器（全枚举精确） | ✅ |
| Boss 盲约束（The Psychic / The Eye / The Arm 等 17 类） | `rules.py` 前置于求解器 | ✅ |
| 商店：买 / 卖牌腾位 / 不买 | Tier 1 Jev Composite Scoring（4 维量表 + 方向权重） | ✅ |
| 跳盲 | 求解器 `can_clear` + Jev Noul 兜底 | ✅ |
| 消耗牌（星球 / 塔罗 / 幻灵） | `use_policy.py` 安全策略 + 商店候选 | ✅ |
| 卡包（小丑 / 标准 / 天体 / 塔罗 / 幻灵包） | Jev Choice 选卡 | ✅ |
| 商店重掷 | Jev Noul | ✅ |
| 卡组方向识别（对子 / 同花 / 顺子 / 高牌 / 均衡） | Jev Choice，加权商店打分 | ✅ |
| 首次通关（Ante 8） | — | 🚧 最深 Ante 6 |

## 仓库结构

```
├── jevatro/                    # 决策引擎（Python）
│   ├── client.py               #   balatrobot JSON-RPC 客户端
│   ├── solver.py               #   Tier 0：出牌/弃牌穷举求解
│   ├── rules.py                #   Boss 盲约束引擎
│   ├── scoring.py              #   牌型识别 + ~80 张小丑效果建模
│   ├── serializer.py           #   gamestate → Jev 紧凑 state 文本
│   ├── card_desc.py            #   266 张卡效果释义库（自动生成）
│   ├── jev_layer.py            #   Tier 1：Jev 批量问答
│   ├── jev_bot.py              #   求解器 + Jev bot
│   ├── llm_layer.py            #   Tier 2：OpenAI 兼容 LLM 臂
│   ├── llm_bot.py              #   求解器 + LLM bot
│   ├── naive_bot.py            #   基线 bot
│   ├── use_policy.py           #   消耗牌安全策略
│   ├── batch_runner.py         #   多种子成对 A/B 批量器
│   ├── ab_report.py            #   成对对比报告
│   ├── cost_report.py          #   token/成本记账（pricing.py）
│   ├── dashboard.py            #   本地 Web 观测台
│   └── analyze_run.py / inspect_jev.py / error_analysis.py …
├── 小丑牌xJev技术方案.md        # 技术方案（12 章）
├── EXECUTION_LOG.md            # 完整迭代日志（13 轮）
├── LLM对比Jev报告.html          # LLM vs Jev 对比报告
├── 公众号文章_jevatro.md         # 公众号叙事文章
└── article_imgs/ ui_review/    # 图表与截图
```

## 快速开始

**前置环境**（Windows，通过 mod 操控游戏）：

| 组件 | 使用版本 | 位置 |
|---|---|---|
| Balatro（Steam 正版） | — | `…\steamapps\common\Balatro` |
| [Lovely](https://github.com/ethangreen-dev/lovely-injector) 注入器 | v0.9.0 | 游戏目录 `version.dll` |
| [Steamodded](https://github.com/Steamopollys/Steamodded) | 26.829.0 | `%AppData%\Balatro\Mods\Steamodded` |
| [balatrobot](https://github.com/coder/balatrobot) | v1.5.2 | `%AppData%\Balatro\Mods\balatrobot`（API 端口 `127.0.0.1:12346`） |

```bash
pip install requests typesafe-sdk

# 配置 key（控制台获取: https://console.typesafe.ai）
cp jevatro/.env.example jevatro/.env    # 编辑 TYPESAFE_API_KEY=...

# 1. 启动游戏（mod 自动监听 12346 端口）
start "" "D:\software\Steam\steamapps\common\Balatro\Balatro.exe"

# 2. 跑 bot（种子任意）
cd jevatro
python naive_bot.py JEVATRO1     # 基线：求解器 + 朴素商店
python jev_bot.py   JEVATRO1     # 求解器 + Jev 商店/盲注/开包
python llm_bot.py   JEVATRO1     # 求解器 + LLM 臂（需 .env 配 LLM_*）

# 3. 观测与分析
python dashboard.py               # → http://127.0.0.1:8765
python analyze_run.py             # 最新一局分析
python inspect_jev.py             # Jev 每题打分与置信度明细
python batch_runner.py 8          # 8 种子 × 3 配置成对 A/B
python ab_report.py               # 成对对比报告
python cost_report.py             # token 与成本记账
```

## 可观测性

每个决策落盘 JSONL（求解器输出、Jev 完整问答与置信度、LLM prompt、成本）。`dashboard.py` 提供深色主题本地 Web 观测台：左栏实时游戏截图 + 局面状态，右栏实时决策流（可展开 Jev/LLM 问答详情）。

![观测台](article_imgs/10_观测台.png)

## 文档

- [小丑牌xJev技术方案](小丑牌xJev技术方案.md)——12 章技术方案：架构、题目集设计、评测矩阵、路线图
- [EXECUTION_LOG.md](EXECUTION_LOG.md)——每轮迭代记录：试了什么、坏了什么、测了什么、回退了什么
- [LLM对比Jev报告](LLM对比Jev报告.html)——Jev vs LLM 成本与能力对比（实测口径）
- [公众号文章](公众号文章_jevatro.md)——项目叙事长文

## 致谢

- [balatrobot](https://github.com/coder/balatrobot)（[beaston](https://github.com/beaston/balatrobot) 原作，coder 维护）——本项目依赖的游戏内 JSON-RPC API
- [Evalatro](https://github.com/alesha-pro/evalatro)、[balatro-gym](https://github.com/cassiusfive/balatro-gym)、[balatro-calculator](https://github.com/EFHIII/balatro-calculator)——方案调研阶段的前置工作
- [Lovely](https://github.com/ethangreen-dev/lovely-injector) 与 [Steamodded](https://github.com/Steamopollys/Steamodded)——mod 技术栈
- [TypeSafe AI](https://typesafe.ai)——Jev / System One 决策模型

## 免责声明

Balatro 是 LocalThunk / Playstack 开发的单机游戏。本项目为个人 AI 实验：需自购 Steam 正版，除标准社区 mod 栈外不改动任何游戏文件，与游戏开发者无关联、未获其背书；所依赖的 mod 生态长期为游戏作者所容忍。
