# 小丑牌（Balatro）× Jev 结合技术方案

> 版本 v1.0 · 2026-09-21
> 前置调研：TypeSafe AI Jev（System One 决策模型）官方文档与生态、Balatro AI 开源生态（balatrobot / Evalatro / balatro-gym / balatro-calculator / GPT-6 Astra 通关项目）

---

## 0. 摘要（TL;DR）

**核心思路：小丑牌的决策天然分为两层——"能精确计算的"和"靠直觉判断的"。前者交给求解器（代码），后者正好是 Jev 这类"哑巴模型"的主场。**

- 出牌/弃牌用**穷举求解器**精确计算（218 种组合内可全枚举），不花一分钱、零延迟；
- 商店买牌、跳盲注、卡组方向（Archetype）识别等**模糊战略判断**交给 **Jev**（Choice/Score/Noul 三种题型、单次 70–500ms、输出免费、输入 $0.042/百万 token）；
- 低置信度决策可**升级（escalate）给 LLM**（可选），形成"求解器 → Jev → LLM"三层漏斗；
- 游戏控制层复用开源 **balatrobot**（游戏内 JSON-RPC 2.0 HTTP API），评测复用 **Evalatro** 的记分法；
- 预期成本：**一整局（到 Ante 8）约 $0.01、决策延迟亚秒级**，比纯 LLM 方案（分钟级延迟、$1–10/局）低 2–3 个数量级。

---

## 1. 调研结论

### 1.1 Jev：只做判断、不做生成的"哑巴模型"

TypeSafe AI 发布的 System One 模型，**不生成自然语言，只返回结构化判断结果**：

| 题型 | 语义 | 返回 |
|---|---|---|
| **Choice** | 从带 key 的候选中选一个 | `choice` + 全候选 `probabilities` + `confidence` |
| **Score** | 按有序等级量表（rubric）打分 | `score`（如 0–4）+ `probabilities` + `confidence` |
| **Noul** | 是非概率判断 | `noul` ∈ [0,1] |

关键工程特性：

- **接口**：`POST https://api.typesafe.ai/v1/systemone`，Bearer 鉴权，模型名 `jev-latest`（当前 jev-1.13.0）；也可走 OpenRouter `~typesafe/jev-latest`。Python SDK：`pip install typesafe-sdk`（读 `TYPESAFE_API_KEY` 环境变量），另有 JS SDK。
- **批处理**：一次调用可混装任意多道题，**并行、隔离**地跑在同一份 `state` 上，加题几乎不增加响应时间——这是本方案商店决策的核心杠杆。
- **经济性**：输入 $0.042/MTok、**输出免费**；端到端延迟 70–500ms；限流约 250K tok/s。
- **置信度**：经 RLCD（Reinforcement Learning for Calibrated Decisions）校准，`confidence` 可直接用于路由（官方 Confidence-Gated Routing 模式）。
- **官方最佳实践**：题目要**原子化**（一个有经验的人几秒内能做的"直觉判断"）；多因子判断拆成多道题，**加权逻辑写在自己代码里**（Composite Scoring 模式），改权重不用改 prompt。

**Jev 的边界**：不能做长链推理、不能生成内容、判断质量依赖 `state` 的表述质量。所以它不能独立"打牌"，但能承担高频、廉价、可校准的直觉判断层。

### 1.2 小丑牌 AI 技术路线全景（截至 2026-09）

| 路线 | 代表项目 | 结论 |
|---|---|---|
| **游戏控制 API** | [balatrobot](https://github.com/coder/balatrobot)（coder 维护，besteon 原作） | 成熟可用。Lovely+Steamodded 之上的 Lua mod，在游戏内起 JSON-RPC 2.0 HTTP 服务（默认 `127.0.0.1:12346`），覆盖完整游戏控制 |
| **LLM 全权决策** | GPT-6 Astra bot（Reddit 用户 Atol8，金注黑牌组多次通关）；[balatrollm](https://github.com/coder/balatrollm) | 已被验证**可行但昂贵**：LLM 管战略 + BalatroBot 管状态/合法性 + Python 数值工具管计算，能通最高难度，但每步 5–30s、单局成本美元级，且仍有低级失误 |
| **LLM 基准评测** | [Evalatro](https://github.com/alesha-pro/evalatro)（alesha-pro） | 把小丑牌变成可复现 LLM benchmark：真实游戏 + balatrobot + TS runner，记录每步决策/token/成本，记分 `progress × legality`，目标 Ante 12；工具注册表还能跑成 MCP server |
| **强化学习** | [balatro-gym](https://github.com/cassiusfive/balatro-gym)（Gymnasium 环境）；果蝇脑 RL（约 20% 白注胜率） | 路线存在但战绩一般：长视野+部分可观测+稀疏奖励，样本效率低；balatro-gym 是**快速迭代模拟器**（Python 规则复现，注意版本保真度），适合做训练环/批量评估 |
| **精确求解器** | [EFHIII/balatro-calculator](https://github.com/EFHIII/balatro-calculator) | 单局面最优出牌已完全解决：给定手牌+小丑+倍率算最高分打法。**说明出牌层根本不需要 AI** |

### 1.3 关键洞察：小丑牌决策天然分层

把一局小丑牌的所有决策点按"是否可精确计算"分类：

| 决策点 | 性质 | 现有最优解 |
|---|---|---|
| 出哪几张牌 / 弃哪几张 | **精确**：≤218 种出牌组合可全枚举，收益可精确算分 | 求解器（零成本、最优） |
| 商店买哪个小丑/道具 | **模糊**：涉及协同、成长性、经济、卡组方向的多维权衡 | LLM 或人类直觉 → **Jev 的 Composite Scoring 正好匹配** |
| 跳过/选择哪个盲注 | **混合**：战力可算，但跳过的长线价值模糊 | 求解器估战力 + **Jev 做风险偏好判断** |
| 开包选哪张 | **模糊**：与构筑方向的匹配度 | **Jev Choice** |
| 卡组方向识别（同花/对子/高牌流…） | **模糊**：看小丑+升级+牌堆趋势的"读牌" | **Jev Noul fan-out → argmax** |
| 小丑替换（卖旧买新） | **混合**：精确算分差 + **Jev 判断协同损失** | 混合 |
| 重掷商店 | **模糊**：期望价值 vs 节奏 | **Jev Noul** |

**这正是心理学里 System 1（快直觉）/ System 2（慢推理）的划分，也是 Jev 命名"System One model"的本意。GPT-6 bot 用大模型同时干了两层的活，贵且慢；本方案把 System 1 的活下放给 Jev，System 2 的活下放给求解器，LLM 只在两者都不确定时兜底。**

---

## 2. 方案定位与目标

三条可选产品形态，建议以 ① 为主线，②③ 为衍生产出：

1. **主线：Jev 驱动的自动打牌 Agent（"Jevatro"）**——求解器+Jev 混合决策引擎，通过 balatrobot 操控真实游戏，目标白注稳定通关（Ante 8+），冲击金注黑牌组。
2. **衍生：实时教练/复盘插件**——人类自己玩，Jev 在商店/盲注界面给建议（70–500ms 延迟足够做到"秒回"），Evalatro 式逐决策日志做复盘。
3. **衍生：提交 Evalatro 基准**——"solver+Jev 混合"作为一个参赛配置，顺带产出 Jev 游戏判断能力的公开数据。

**非目标**：不修改游戏本体逻辑、不做任何联网对战用途（小丑牌是单机游戏，社区 mod 生态被官方容忍；须自购 Steam 正版）。

---

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     决策引擎（外部进程，Python）               │
│                                                             │
│  ┌───────────────┐   ┌──────────────────┐   ┌────────────┐  │
│  │ Tier 0 求解器  │   │  Tier 1 Jev 层    │   │ Tier 2 LLM │  │
│  │ 出牌/弃牌穷举   │   │  商店/盲注/方向识别 │   │ 低置信兜底  │  │
│  │ 精确算分(本地)  │   │  Choice/Score/Noul│   │ (可选开关)  │  │
│  └──────┬────────┘   └────────┬─────────┘   └─────┬──────┘  │
│         │     confidence < τ 时升级 ──────────────▶│         │
│         └────────────────┬─────────────────────────┘         │
│                          ▼                                   │
│                 回合决策循环（状态机）                          │
└──────────────────────────┬──────────────────────────────────┘
                           │ JSON-RPC 2.0 over HTTP
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Balatro（Steam 正版）+ Lovely 注入器 + Steamodded +         │
│  balatrobot mod（监听 127.0.0.1:12346）                       │
└─────────────────────────────────────────────────────────────┘
```

组件职责：

| 组件 | 职责 | 复用/自研 |
|---|---|---|
| balatrobot | 游戏状态读取 + 全量动作执行 | 复用开源 |
| 状态序列化器 | 把 `gamestate` 压缩成 Jev 可读的紧凑文本 | 自研（~100 行） |
| 求解器（Tier 0） | 枚举出牌组合、精确算分、算弃牌期望 | 自研算分核（规则公开）或移植 balatro-calculator |
| Jev 决策层（Tier 1） | 商店 composite scoring、盲注 Noul、方向识别 fan-out | 自研题目集 + typesafe-sdk |
| LLM 兜底（Tier 2） | 低置信度场景的深度推理 | 可选，OpenAI 兼容任意端点 |
| 评测器 | 固定种子批量跑局、Evalatro 记分、A/B 报告 | 复用 Evalatro 记分法 + 自研批跑 |
| 日志器 | 逐决策记录 state/题目/回答/置信度/动作/成本 | 自研（JSONL） |

**语言选型：Python 3.10+**。理由：typesafe-sdk 官方 Python 支持；balatrobot 官方示例 bot 是 Python；求解器数值计算生态最好；Evalatro runner 是 TS 但只借鉴其记分协议，不必跟随。

---

## 4. 基础设施层：balatrobot 接入

### 4.1 安装

1. Steam 购买并安装 Balatro（Windows/macOS 原生，Linux 走 Proton 实验性 attach 模式）；
2. 装 [Lovely](https://old.thunderstore.io/c/balatro/)（运行时 Lua 注入器）+ [Steamodded](https://github.com/Steamodded/smods)（mod 框架）；
3. 把 balatrobot 丢进 `Mods/` 目录，启动游戏后即监听 `http://127.0.0.1:12346`。

### 4.2 本方案用到的 API 面（JSON-RPC 2.0）

| 方法 | 参数 | 用途 |
|---|---|---|
| `health` / `gamestate` | — | 健康检查 / 全量状态（含 jokers、hand、shop、blinds、money、ante…） |
| `start` | `deck`, `stake`, `seed`? | **可控种子开局**（评测可复现的关键） |
| `select` / `skip` | — | 选盲 / 跳盲（Boss 盲不可跳） |
| `play` | `cards: int[]`（手牌索引） | 出牌 |
| `discard` | `cards: int[]` | 弃牌 |
| `buy` / `sell` / `reroll` / `pack` | 商店/背包索引 | 商店全套操作 |
| `use` | `consumable`, `cards?` | 使用塔罗/星球等消耗牌 |
| `cash_out` / `next_round` | — | 回合结算 / 离开商店 |
| `save` / `load` | `path` | 存档点（评测与调试） |
| `add` / `set`（debug） | — | **仅限调试，评测期禁用** |

错误码 `-32002 INVALID_STATE` / `-32003 NOT_ALLOWED` 即天然合法性校验。

```python
import requests

class BalatroClient:
    def __init__(self, url="http://127.0.0.1:12346"):
        self.url, self._id = url, 0

    def call(self, method, **params):
        self._id += 1
        r = requests.post(self.url, json={
            "jsonrpc": "2.0", "id": self._id, "method": method, "params": params
        }, timeout=30)
        payload = r.json()
        if "error" in payload:
            raise RuntimeError(f"{method}: {payload['error']}")
        return payload["result"]
```

---

## 5. Tier 0：精确求解器（不需要 AI 的部分）

**职责**：给定 `gamestate`，回答"这手牌怎么打/怎么弃最优"。

- 手牌上限 8 张，出牌组合 ΣC(8,k), k=1..5 = **218 种**，全枚举无压力；
- 算分核按公开计分规则实现（底分×等级 → chips × mult，小丑触发顺序按在场顺序）；
- 输出：最高分打法、各候选打法分数表、以及"预计 N 手内能否过盲"（当前盲需求 chips ÷ 最优单手期望 → 与剩余手数比较）；
- 该分数表同时**喂给 Jev 层**作为事实基础（见 §6.1），让 Jev 只判断"分数之外"的东西。

> 实现 amortization：先移植 [EFHIII/balatro-calculator](https://efhiii.github.io/balatro-calculator/) 的算分逻辑（JS，可用子进程或翻译成 Python），或直接按规则自写。规则测试用 balatrobot 的 `set`/`add` 构造固定局面做对拍。

**弃牌搜索**是求解器里唯一带启发式的部分（弃牌是面向未来的：想凑同花/顺子）。M1 阶段用简单启发（保留人数最多的目标牌型），M3 阶段可让 Jev 出"留牌方向"的 Choice（见 §6.4）。

---

## 6. Tier 1：Jev 判断层设计（本方案核心）

### 6.1 状态序列化：Jev 的 `state` 怎么写

Jev 的判断质量取决于 state 表述。原则：**紧凑、结构化、面向判断**（不是 dump 全量 JSON）。

```
[局] Ante 3/8, 盲注需求 2400 chips, 底注$5, 金币$28, 手数4/4, 弃数3/3
[构筑方向-同花流] 手牌等级: 同花L4(40×4), 对子L2, 高牌L1
[小丑] 1. j_fortune_teller(每张塔罗+1 mult, 现×23)  2. j_blueprint(复制左侧)
[手牌] ♠A ♥3 ♦3 ♣3 ♠7 ♥9 ♦J ♣2
[商店] 小丑: j_hologram(稀有,买包永久+15mult,现×1) $7 / j_even_steven(偶数牌+4mult) $4
       星球: Planet Mars(对子升级) $3  塔罗: The Hermit(加倍金钱) $4  背包: $4
[求解器事实] 最优打法: 3♥3♦3♣ 对子 = 312分; 4手满打预计 1100/2400 (不足)
```

要点：小丑用社区标准 key（`j_xxx`）+ 一句话人话释义（Jev 是语义模型，不认识 Balatro 专有 key，**必须带释义**）；末尾附求解器算出的事实，让 Jev 的题目只聚焦在判断上。

### 6.2 商店决策：Composite Scoring（官方模式直接套用）

对商店里每个可买项 + （可选）背包内容，一次 Jev 调用批量打四个维度（5 级 rubric，0–4），代码里加权求和：

```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

jev = TypeSafeClient()

SHOP_RUBRIC = {
    "synergy": Score(
        instructions="该商品与当前小丑/牌型等级的协同程度",
        criteria=[
            "0 与现有构筑零交互或机制冲突",
            "1 略有相关但方向不符",
            "2 中性填充,不拖后腿",
            "3 明确加强现有方向",
            "4 核心拼图,直接改变战力曲线",
        ],
    ),
    "scaling": Score(
        instructions="该商品的长期成长性(本局剩余局数视角)",
        criteria=["0 无成长", "1 一次性", "2 轻微成长", "3 稳定成长", "4 复利式成长"],
    ),
    "economy": Score(
        instructions="该商品对金钱/利息循环的贡献",
        criteria=["0 纯花钱无回报", "1 略亏", "2 回本", "3 产出>成本", "4 直接利息引擎"],
    ),
    "immediate": Score(
        instructions="立刻解掉当前盲注燃眉之急的程度",
        criteria=["0 无助", "1 微弱", "2 有些帮助", "3 明显", "4 本回合就靠它"],
    ),
}

def score_shop(state_text: str) -> list[dict]:
    questions = {}
    items = current_shop_items()          # [{key, desc, price, slot}, ...]
    for it in items:
        for dim, q in SHOP_RUBRIC.items():
            questions[f"{it['slot']}__{dim}"] = Score(
                instructions=f"商品[{it['desc']}, ${it['price']}] 的{q.instructions}",
                criteria=q.criteria,
            )
    resp = jev.system_one(state=state_text, questions=questions)  # 一次调用,全部并行
    out = []
    for it in items:
        a = resp.answers
        norm = lambda d: a[f"{it['slot']}__{d}"].score / 4
        out.append({
            **it,
            "conf": min(a[f"{it['slot']}__{d}"].confidence for d in SHOP_RUBRIC),
            "value": 0.40*norm("synergy") + 0.25*norm("scaling")
                   + 0.15*norm("economy")  + 0.20*norm("immediate"),
        })
    return sorted(out, key=lambda x: -x["value"])
```

**权重即策略**：四个权重是公开、可调、可按"卡组方向"切换的配置——这就是官方 Composite Scoring 模式"改系数不改 prompt"的优势。比如经济紧张期把 `economy` 权重临时上调。

**买与不买**：`value` 高且买得起 → 买；再补一道 Noul 门闩：

```python
"should_buy_top": Noul(instructions=(
    f"买下{top['desc']}(${top['price']})后的金币为${after}，"
    "考虑到利息结算与后续商店，此刻买入是合理的"))
```

### 6.3 卡组方向识别：Noul Fan-out + Intent Routing（决定权重表）

每个商店进入时，一次调用批量问一组 Noul：

```python
ARCHETYPES = {
    "flush":    "当前构筑正走同花/花色方向",
    "pair":     "当前构筑正走对子/满堂方向",
    "highcard": "当前构筑正走高牌+X多倍小丑方向",
    "straight": "当前构筑正走顺子方向",
    "econ":     "当前处于攒钱/经济运营阶段",
    "chips":    "当前缺少乘区,需要的是mult类小丑",
}
questions = {k: Noul(instructions=v) for k, v in ARCHETYPES.items()}
probs = {k: a.noul for k, a in resp.answers.items()}
archetype = max(probs, key=probs.get)   # → 切换 §6.2 的权重表 W[archetype]
```

官方文档明确：**一次调用内所有题目并行、隔离执行，加题几乎不加延迟**——所以 6.2+6.3 合并成每次进商店**一次 Jev 调用**（10–30 道题），延迟仍是 70–500ms 一档。

### 6.4 其他决策点的题目设计

| 决策点 | 题型 | 题目示意 |
|---|---|---|
| 选盲/跳盲 | Noul ×2 | "求解器预计 3 手内过此盲概率不足，跳过它换下一阶段tag是合理的" / "以当前战力打 Boss盲(效果:手牌-1)风险可接受" |
| 卖小丑腾位 | Choice | criteria=各小丑 key+释义，instructions="若必须卖一个为{新小丑}腾位，卖哪个损失最小" |
| 重掷商店 | Noul | "当前商店无任何 value>0.5 的商品,花${x}重掷的期望优于直接离店" |
| 开包选择 | Choice | criteria=包内每张牌的 key+释义，instructions="对{archetype}方向最有价值的是" |
| 弃牌方向（进阶） | Choice | criteria=[保留同花/保留对子/弃最高牌…] 指导求解器的弃牌启发 |
| 消耗牌使用 | Noul/Choice | "The Hermit 现在用掉 vs 攒到商店后用,哪个更好" |

### 6.5 置信度路由：三层漏斗的切换规则

```python
def decide(decision_point, state):
    fact = solver.facts(state)            # Tier 0: 精确事实
    if fact.is_forced:                    # 唯一合法/唯一可行动作
        return fact.action, {"tier": 0}

    ans = jev_decide(decision_point, state, fact)   # Tier 1
    if ans.confidence >= TAU:             # 默认 TAU=0.62,按校准曲线调
        return ans.action, {"tier": 1, "conf": ans.confidence}

    if LLM_ENABLED:                       # Tier 2: 可选
        return llm_decide(decision_point, state, fact), {"tier": 2}
    return ans.safe_default, {"tier": 1, "fallback": True}   # 保钱、跳过、不动
```

要点：
- **每个决策点都定义 `safe_default`**（通常是"不买/不卖/不重掷"），Jev 不确定时的保守动作几乎无副作用——这是 Jev 校准置信度带来的独特安全性质；
- τ 不拍脑袋：评测期画 reliability diagram，取"置信度≥τ 时实际正确率≥85%"的最小 τ；
- Tier 2 的 prompt 里带上 Jev 的概率分布作为先验（"模型认为是 A(0.55) vs B(0.45)"），显著减少 LLM 的无谓发散。

### 6.6 Jev 作为 LLM 模式的守门员（如果走 LLM 主导路线）

如果对比实验里让 LLM 全权决策，每步执行前加一道廉价 Jev Noul 复核："该动作在此状态下明显有害吗（如卖掉唯一成长引擎/跳过必过的盲）"——`noul > 0.5` 则拒绝并要求重选。相当于给 GPT-6 方案加一层 $0.0001/步的护栏。

---

## 7. 回合决策循环（伪代码）

```python
def run_one_game(deck, stake, seed, profile):
    bot = BalatroClient()
    jev = JevLayer(profile)                 # 权重表 + 题目集
    st = bot.call("start", deck=deck, stake=stake, seed=seed)
    while True:
        gs = bot.call("gamestate")
        state_text = serialize(gs)          # §6.1
        log.begin_turn(gs, state_text)

        phase = gs["state"]
        if phase == "BLIND_SELECT":
            act = decide("blind", state_text)          # select / skip
            gs = bot.call("skip" if act == "skip" else "select")
        elif phase == "SELECTING_HAND":
            play, conf = solver.best_play(gs)           # Tier 0 直出
            if solver.will_clear(gs):                   # 能过:最省手数打法
                gs = bot.call("play", cards=play)
            else:
                direction = decide("discard_dir", state_text)  # Jev 指方向
                gs = bot.call("discard", cards=solver.best_discard(gs, direction))
        elif phase == "ROUND_EVAL":
            gs = bot.call("cash_out")
        elif phase == "SHOP":
            batch = jev.shop_batch(state_text)          # §6.2+6.3 一次调用
            for action in plan_shop_actions(batch):     # 买/卖/重掷/买包排序
                gs = execute(bot, action)
            gs = bot.call("next_round")
        elif phase == "OPENING_BOOSTER":
            pick = decide("booster", state_text)        # Choice
            gs = bot.call("pack", card=pick)
        elif phase == "GAME_OVER" or won(gs):
            break
        log.end_turn()
    return summarize_run(log)
```

关键点：**出牌是求解器直出的（Tier 0），每个商店只发生 1 次 Jev 调用（批量），每个盲注选择最多 1 次**——单局 Jev 调用次数约 100–150 次。

---

## 8. 评测方案

### 8.1 记分：沿用 Evalatro 协议

- `progress = 阶梯位置 / (目标Ante × 3)`（目标 Ante 12；过 Ante 8 只是里程碑）；
- `legality = 1 - 非法动作数/总动作数`（balatrobot 错误码直接统计）；
- `score = round(progress × legality × 100, 1)`；
- 每局落盘 JSONL：每步的 state 快照、Jev 题目与回答（含 confidence）、动作、token、成本、结局。

### 8.2 实验矩阵（固定种子集，可复现）

| 配置 | 说明 |
|---|---|
| A. naive 基线 | 确定性脚本（打最高分牌、见啥买啥），零 token，对照下界 |
| B. solver-only | 只用 Tier 0，商店用固定启发，量化"直觉层"的价值 |
| C. solver+Jev | 本方案主配置 |
| D. solver+Jev+LLM 兜底 | 量化 Tier 2 的边际收益 vs 成本 |
| E. 纯 LLM（可选） | 复现 GPT-6 路线作参照 |

- 种子集：50 个固定 seed × 白注起步；主配置达标后上金注黑牌组（GPT-6 bot 的标尺）；
- 双轨评估：**快速迭代用 balatro-gym**（无头、秒级、批量），**验收用真实游戏 + balatrobot**（保真度、记分可提交 Evalatro）；
- 指标：胜率、平均到达 Ante、score、单局成本($)、单步决策延迟、Tier 0/1/2 动作占比、Jev 置信度-正确率校准曲线、按决策点分桶的错误率（哪类决策最弱→迭代题目集）。

### 8.3 题目集迭代流程

日志 → 分桶错误率 → 修 rubric 措辞/加维度/调权重 → 固定种子回归 → 只留胜率提升的改动。**题目集就是本项目的"模型权重"，纳入版本管理。**

---

## 9. 成本与延迟测算

按单局（Ante 8 通关，~24–30 轮）估算：

| 项 | Jev 混合方案 | 纯 GPT-6 类 LLM |
|---|---|---|
| 决策调用 | ~120 次（进商店/盲注各 1 次批量） | ~400+ 步每步一次 |
| 每次输入 | ~1.5–2K tokens（紧凑 state） | ~2–5K tokens（+生成） |
| 单局输入 token | ~0.2M → **$0.008** | ~1.5M+ 输出另计 → **$1–10** |
| 单步延迟 | 求解器 <10ms；Jev 70–500ms（含 20+ 道题批量） | 5–30s/步 |
| 单局 API 时间 | ~1 分钟 | 20–60 分钟 |

（Jev 输出免费、限流 250K tok/s 对本场景等于无限制；即使全量 A/B 实验矩阵 250 局 ×5 配置也只要 ~$10。）

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| Jev 对游戏策略的判断力未知（非专门训练） | 商店决策质量不达预期 | 架构上 Jev 只接模糊决策，精确层兜底；rubric 工程化迭代；8.2 的 C vs B 实验直接量化其增量 |
| Jev 早期访问，API/行为可能变 | 线上断裂 | 走 OpenRouter `~typesafe/jev-latest` 双通道；SDK 锁版本；题目集与调用层解耦 |
| state 序列化质量决定一切 | 判断漂移 | 释义库覆盖全部 150 小丑（社区 wiki 抓取生成），缺省回退到商品描述原文 |
| 游戏版本更新破坏 mod 链（Lovely/Steamodded/balatrobot 三层依赖） | 停摆 | 锁定游戏版本（Steam beta 分支）；balatro-gym 快速轨不受影响 |
| balatrobot debug 接口污染评测 | 成绩无效 | 评测配置硬禁用 `add`/`set`，记分器校验动作白名单 |
| 置信度路由阈值失准 | 过度升级 LLM 或过度保守 | 每次评测重画校准曲线调 τ；safe_default 设计保证保守侧错误无副作用 |
| 商业/合规 | — | 单机游戏、自购正版、本地 mod，社区惯例允许；不接入任何真实货币博弈场景 |

---

## 11. 实施路线图

| 里程碑 | 周期 | 交付物 | 验收标准 |
|---|---|---|---|
| **M1 基础设施** | 1–2 周 | balatrobot 跑通；naive bot（配置 A）能完整打完一局；算分核与 balatro-calculator 对拍通过；JSONL 日志 | 配置 A 在 50 seed 上产出基线分布 |
| **M2 Jev 决策层** | 2–3 周 | 状态序列化器 + 小丑释义库；商店 composite scoring + 盲注 Noul 上线（配置 C） | C 的 score 均值 > B（solver-only）；白注胜率 ≥ 40% |
| **M3 方向识别与路由** | 2 周 | archetype fan-out + 权重表切换 + 置信度路由 + 校准曲线；可选 LLM 兜底（配置 D） | 白注稳定通关（≥70%）；D 的增量/成本比给出结论 |
| **M4 冲高与产出** | 持续 | 金注黑牌组挑战；Evalatro 提交；教练插件原型（screenshot + 建议浮层） | 金注黑牌组至少 1 胜；公开技术报告 |

---

## 12. 参考资料

**Jev / TypeSafe AI**
- [TypeSafe AI 官方博客：Introducing System One Models & Jev](https://typesafe.ai)（定价、延迟）
- [官方文档 Quickstart](https://docs.typesafe.ai/introduction/quickstart.md) · [Primitives](https://docs.typesafe.ai/primitives.md) · [Patterns](https://docs.typesafe.ai/patterns.md) · [Composite Scoring](https://docs.typesafe.ai/patterns/composite-scoring.md) · [Confidence-Gated Routing](https://docs.typesafe.ai/patterns/confidence-routing.md)
- [OpenRouter: Jev 1.13](https://openrouter.ai)
- [微信原文：《一文看懂外网爆火的哑巴模型 jev，10 个实测案例分享》](https://mp.weixin.qq.com/s/r3hCizR8d-DY9K3H2iPSqw)

**Balatro AI 生态**
- [coder/balatrobot（BalatroBot）](https://github.com/coder/balatrobot) · [API 文档](https://coder.github.io/balatrobot/latest/)（JSON-RPC @ 12346）
- [alesha-pro/evalatro](https://github.com/alesha-pro/evalatro)（LLM 基准，记分协议） / [evalatro.dev](https://evalatro.dev)
- [coder/balatrollm](https://github.com/coder/balatrollm)（官方 LLM bot）
- [Tom's Hardware：GPT-6 Astra 通关金注黑牌组](https://www.tomshardware.com/tech-industry/artificial-intelligence/ai-enthusiast-builds-gpt-6-astra-powered-bot-to-take-on-balatros-gold-stake-black-deck-bot-leverages-python-for-numerical-tools-beats-hardest-difficulty-repeatedly)
- [cassiusfive/balatro-gym](https://github.com/cassiusfive/balatro-gym)（RL Gymnasium 环境）
- [EFHIII/balatro-calculator](https://github.com/EFHIII/balatro-calculator)（精确算分器）
- [Steamodded/smods](https://github.com/Steamodded/smods) · [Lovely (Thunderstore)](https://old.thunderstore.io/c/balatro/)
