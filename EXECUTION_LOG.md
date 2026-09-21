# Jevatro 执行记录（Agent Execution Log）

> 本文档记录小丑牌 × Jev 项目从调研到实现的全部执行过程，由 ZCode agent 自动维护。
> 项目路径：`D:\AI项目\小丑牌\` · 决策引擎：`jevatro\`

---

## 第一轮迭代（2026-09-21 晚）—— 调研 + M1 基础设施 + MVP

### 1. 技术调研
- 研读微信文章《一文看懂外网爆火的哑巴模型 jev》，确认 Jev = TypeSafe AI 的 System One 决策模型
  （Choice/Score/Noul 三题型、输出免费、70–500ms、RLCD 校准置信度）。
- 调研 Balatro AI 生态：balatrobot（JSON-RPC 游戏控制）、Evalatro（LLM 基准）、GPT-6 Astra 通关项目、
  balatro-gym（RL 环境）、balatro-calculator（精确算分器）。
- 产出《小丑牌×Jev 结合技术方案》（md + html 双格式，12 章，含三层架构/题目集设计/评测矩阵/路线图）。

### 2. 环境部署（Windows，游戏装在 D:\software\Steam\steamapps\common\Balatro）
| 步骤 | 内容 | 结果 |
|---|---|---|
| 2.1 | 下载 Lovely v0.9.0（`version.dll` → 游戏目录） | ✅ |
| 2.2 | 下载 Steamodded 26.829.0 → `%AppData%\Balatro\Mods\Steamodded` | ✅ |
| 2.3 | 下载 balatrobot v1.5.2 → `%AppData%\Balatro\Mods\balatrobot` | ✅ |
| 2.4 | 启动游戏验证 JSON-RPC（`127.0.0.1:12346`） | ✅ health/gamestate 正常 |

### 3. Python 工程 `jevatro/`
- `client.py`：BalatroBot JSON-RPC 客户端（错误码异常、状态等待）。
- `scoring.py`：算分核——13 种牌型识别、计分卡选择、45 张静态小丑效果表、增强/版本修饰。
- `solver.py`：出牌求解器，全枚举 ≤218 组合。
- `naive_bot.py`：状态机主循环（BLIND_SELECT/SELECTING_HAND/ROUND_EVAL/SHOP/开包兜底）。
- `logger.py`：JSONL 逐决策日志；`test_scoring.py` 12 项单测全过。

### 4. 踩坑记录（第一轮）
| 坑 | 现象 | 修复 |
|---|---|---|
| 真实 schema 与文档不符 | `modifier`/`state` 是 list 不是 dict | scoring 用 `mods()` 兼容两种形式 |
| `deck` 字段歧义 | `gamestate["deck"]` 是牌组名字符串不是卡区 | 求解器改读 `cards` 区 |
| Boss 盲约束 | The Psychic（必须出 5 张）导致 play 被拒 | 求解器输出失败时退化为前 5 张 |

### 5. MVP 结果（配置 A/B，种子 JEVATRO1）
- **完整一局全自动**：29 动作 / 0 非法 / 71.5 秒 / Ante 2 Boss 阵亡。
- 日志：`logs/run_naive_20260921_232422.jsonl`（每个动作含求解器输出与前后状态）。

---

## 第二轮迭代（2026-09-21 深夜）—— M2：Jev 决策层 + Web 面板 + 本文档

### 1. Jev 接入
- `pip install typesafe-sdk`（0.7.0）；key 配置于 `jevatro/.env`（TYPESAFE_API_KEY）。
- 探针验证（`probe_jev.py`）：三题型真实返回 —— Noul 0.17（非同花方向，判断合理）、
  Choice+置信度、Score 1.75+校准曲线正常。**API 打通，key 有效。**

### 2. 语义资产
- `build_card_desc.py`：从 balatrobot 文档提取 **266 张卡**（150 小丑/52 消耗/32 兑换券/32 卡包）
  的 key→效果描述字典 → `card_desc.py`（Jev state 的释义底座）。
- `serializer.py`：gamestate → 紧凑中文 state 文本（局况/盲注/牌型等级/小丑释义/手牌/商店/求解器事实）。

### 3. Jev 决策层（`jev_layer.py`）
- **商店**：Composite Scoring——每商品 4 维 Score（synergy/scaling/economy/immediate，5 级 rubric）
  + archetype fan-out（5 个 Noul 方向识别）+ 重掷 Noul，**全部混装一次 system_one 调用**；
  代码层做可行性过滤（金币/槽位）、加权求和（方向权重与 default 50/50 混合）、价值阈值购买。
- **盲注**：求解器判定能过/不能跳过则免调用；否则单题 Noul（跳过阈值 0.65）。
- **回退**：Jev API 失败 → naive 商店策略，保证对局永不中断。
- `jev_bot.py`：求解器出牌 + Jev 商店/盲注 + Planet 即买即用。

### 4. 踩坑记录（第二轮）
| 坑 | 现象 | 修复 |
|---|---|---|
| balatrobot 上游 bug | `menu()` 后 `start` 崩：`viewed_back (a nil value)`（start.lua:116） | 给已安装 mod 打补丁：`if G.GAME.viewed_back then ... end`；bot 加 start 重试 |
| jev_bot 死循环隐患 | start 失败后空转 else 分支 | 重试 3 次 + 明确退出 |
| 兑换券元组 | vouchers 二元组致解包崩溃 | 改三元组 |
| **置信度误用（第一版调参教训）** | conf=0.0 频繁出现（"无信号"而非"不可靠"），min_conf≥0.40 硬门 + 0.55 价值阈 + econ 方向权重稀释 → **零购买**，Ante 1 阵亡（naive 都能到 Ante 2） | 调参：TAU 0.55→0.40、置信度只记录不门控、方向权重与 default 各半 |
| 待打盲注状态 | BLIND_SELECT 时待打盲状态是 `SELECT` 不是 `CURRENT`，查漏后对 Boss 发出 skip 被拒（1 次非法） | 查找 `status in (CURRENT, SELECT)`，BOSS 直接 select 不问 Jev |
| state 噪音 | 商店卡显示 `[enhancement]` 裸键名 | `_mods_brief` 过滤元键名 |

### 5. 实测数据（种子 JEVATRO1，红牌组白注）
| 配置 | 结果 | Jev 调用 | 商店行为 | 单手最高分 |
|---|---|---|---|---|
| naive（基线） | Ante 2 r4 阵亡 | 0 | 买 2 小丑 | 316 |
| jev v1（门槛过严） | Ante 1 r3 阵亡 | 5 / 3.1s | 零购买 | 316 |
| jev v3（调参后） | Ante 2 r5 阵亡 | 14 / 7.7s | 4 购买 + 首次自主跳盲（1 非法：Boss 误 skip） | 2071 |
| **jev v4（Boss 修复）** | **Ante 2 r5 阵亡 · 0 非法** | **12 / 6.6s** | 4 购买（misprint/Saturn/burnt/faceless） | **2071** |

**Jev 增值的直接证据**：
- j_misprint 买入后单手 Flush 284 → **1136**（4 倍）；
- c_saturn（星球卡）买入即用升级顺子 → 单手 Straight **2071**（基线 6.5 倍）；
- 小盲自主跳过决策（noul 0.66 > 0.65 阈值）——基线永远只会 select；
- Jev 平均延迟 0.55s/次（批量 20+ 题），符合 70–500ms 官方标称量级。

### 6. 决策面板（`dashboard.py`）
- 纯标准库本地 Web（`http://127.0.0.1:8765`）：运行列表（含进行中实时刷新）、
  逐决策时间线、Jev 问答展开（state 原文/题目/回答/置信度条）、动作/结果筛选。

---

## 环境与复现速查

```bash
# 启动游戏（带 mod，自动监听 12346）
start "" "D:\software\Steam\steamapps\common\Balatro\Balatro.exe"

# 跑 bot
cd D:\AI项目\小丑牌\jevatro
python naive_bot.py JEVATRO1      # 基线
python jev_bot.py   JEVATRO1      # Jev 驱动

# 面板 / 分析
python dashboard.py               # → http://127.0.0.1:8765
python analyze_run.py             # 最新日志分析
python inspect_jev.py             # Jev 打分明细
```

## 待办（第三轮迭代候选）
- [ ] A/B 多种子批量（50 seeds：naive vs jev 胜率分布）
- [ ] Tarot 使用策略 + 卡包购买（Choice 题型尚未实战）
- [ ] 弃牌搜索（Jev 出留牌方向 Choice）
- [ ] 小丑效果表补全动态卡（ride_the_bus/green_joker 等成长型）
- [ ] Evalatro 记分法接入（progress × legality）
