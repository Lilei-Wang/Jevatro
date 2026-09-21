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

## 第三轮迭代（2026-09-22 凌晨）—— git 环境 + 规则引擎 + 3 轮连续迭代

### 0. git 环境
- 安装 Git 2.55（winget），`git init -b main`，本地身份 `WangLillei <wanglillei@users.noreply.github.com>`
  （**推 GitHub 前请改成你自己的邮箱**）。
- `.gitignore`：`.env`（API key 永不入库）、`_downloads/`、`logs/*.jsonl`；`.env.example` 提供模板。
- 首次提交 `ebee32a`：方案 + jevatro M1/M2 全部代码（24 文件）。
- **推 GitHub 步骤**：在 GitHub 新建空仓库后执行
  `git remote add origin https://github.com/<你的用户名>/<仓库名>.git && git push -u origin main`

### 1. 迭代 3：Boss 盲规则引擎（commit 见 log）
**问题实锤**：The Psychic（必须出5张）下，bot 出 4 张牌 API 不报错但 **0 分白烧一手**（chips 0→0 还扣手数）。
**方案**：`rules.py` 把 17 类 Boss 约束前置于求解器枚举层：
- The Psychic → 只枚举 5 张组合；
- 花色 Boss（Club/Goad/Head/Window）→ 该花色弱化牌 0 筹码 0 效果（仍计牌型，符合游戏规则）；
- The Eye / The Mouth → 牌型白名单/黑名单过滤（用 `played_this_round` 数据）；
- The Arm / The Flint → 牌型等级修正（BASE_AND_INC 表按级增量回算）；
- The Ox → 打"最多使用牌型"会清金币，有 ≥90% 替代时避开。
- 另加**弃牌策略** `best_discard`：打不过时保留最优组合方向（同花≥3/同点数≥2），弃边缘牌≤5张。
**验证**：JEVATRO1 The Psychic 轮全 5 张、每手有分（0→380→1268），白烧手根除；达 ante2 r6。
**测试**：`test_rules.py` 6 组断言全过。

### 2. 迭代 4：商店策略升级 + 竞态修复
- **早期战力优先**：金币<15 或小丑<3 时禁用 econ 方向（fan-out 里偏热）；
- **卖牌腾位**：槽满时加 Jev Choice 题"卖谁损失最小"，新小丑 value≥0.58 才换；
- **动态小丑估值**：补 36 张成长型小丑的中局近似值（green_joker/ride_the_bus/obelisk/photograph/baron 等），
  之前按 0 计导致低估弃买；
- **balatrobot buttons 竞态修复**（上游 bug ×2）：发牌动画中调 play/discard 时 `G.buttons` 为 nil
  → Lua 崩溃 → 客户端无限重试 51 次非法。mod 端（play.lua/discard.lua）补 `if not G.buttons then 返回可重试错误`，
  客户端 `act()` 对 "not ready" 自动等待 0.6s×8 重试。修复后 0 非法。

### 3. 迭代 5：多种子 A/B 批量（`batch_runner.py`）
**5 种子 × 2 配置首轮结果**（修复前）：

| 种子 | naive | jev | 胜者 |
|---|---|---|---|
| JEVATRO1 | ante2 r5 | ante2 r6 | jev |
| JEVATRO2 | ante2 r5 | ante2 r6 | jev |
| JEVATRO3 | **ante3 r9** | ante2 r4 | naive |
| JEVATRO4 | ante4 r12 | **ante5 r13**（3非法） | jev |
| JEVATRO5 | ante1 r3 | ante1 r3 | 平（坏种子） |
| **平均 Ante** | **2.40** | **2.40** | 打平 |

**暴露的两个 bug + 一条策略**：
1. **多买索引位移**：一次计划买多张 → 第二张用旧索引（`-32001 Card index out of range`）和过期槽位判断
   → 修复：每计划限 1 张卡牌 + 1 张兑换券（卖+买可共存），执行后重新规划，状态签名防死循环；
2. **Jev 过于保守**：JEVATRO3 只买 3 件（naive 见啥买啥反而 ante3）→ 修复：小丑<3 时 JOKER 阈值 0.40→0.32；
3. JEVATRO5 是坏种子（ante1 Boss 需 600），两配置同样死于 ante1。

**修复后复验（3 种子）**：全部 **0 非法**；JEVATRO4 = **ante4 r12**（25 次 Jev 调用 14.7s，单手 5478），
JEVATRO3 = ante2 r4，JEVATRO5 = ante1 r3。

### 4. 本轮结论（诚实评估）
- **正确性**：白烧手/非法动作全部根除（0 illegal 稳定），规则引擎 + 竞态修复 + 索引修复是确定性收益；
- **战绩**：单种子峰值 ante4~5，平均与 naive 打平——**Jev 层的边际胜率价值尚未证明**（M2 验收标准
  "C 的 score 均值 > B" 未达成），瓶颈在题目集/权重还需要按 §8.3 的分桶错误率流程迭代，
  以及缺少 Tarot/卡包/弃牌方向的 Jev 决策（第三轮迭代范围外）。

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

---

## 第四轮迭代（2026-09-22）—— 消耗牌支持 + 有/无 Jev 深度对比

### 1. 消耗牌（星球/塔罗/幻灵）购买与使用
**问题**：此前商店候选只放行 JOKER/PLANET/VOUCHER，塔罗幻灵从不购买（用户指出）。
**实现**：
- `use_policy.py`：45 张消耗牌的用法策略——
  - 强化类塔罗（皇后/大祭司等）→ 目标=最优出牌的计分卡（best2/best1）；
  - 花色转换（星星/月亮/太阳/世界）→ 主花色以外的牌（≤3张，方向不符则留着）；
  - 力量（点数+1）→ 最优组合里成对的点数；倒吊人（毁灭）→ 边缘牌瘦身；
  - 印记/版本幻灵 → 最佳计分卡；金钱类（隐士/节制）→ SHOP 阶段且金币≥8；
  - 星球/生成类 → 无目标直接用；
  - NO_BUY 清单（8 张无安全用法/副作用大）：c_death/c_sigil/c_ouija/c_ectoplasm/
    c_immolate/c_ankh/c_wraith/c_hex。
- 使用时机：SELECTING_HAND 先用手牌目标类；SHOP 收尾用无目标+金钱类；跳过机制防死循环。
**验证**：`test_consumables.py` 集成测试（debug add 注入）——皇后塔罗强化 2 张最佳卡、
土星星球顺子 1→2 级，全部通过。

### 2. 深度 A/B 对比（`ab_report.py`）
按 (种子, 配置) 取最新一局成对解析 JSONL。指标：Ante/轮、最大单手分、全场总得分、
购买数、消耗牌使用数、跳盲数、弃牌数、非法数、Jev 调用次数/延迟/成本估算。
8 种子 × 2 配置 = 16 局批量（`batch_runner.py 8`），结果：logs/ab_report.md。

### 3. 8 种子 × 2 配置批量结果（2026-09-22 01:36，全部为消耗牌功能后新数据）

| 种子 | 无Jev: Ante/轮 | 有Jev: Ante/轮 | 胜者 | 最大单手(无/有) | 总得分(无/有) |
|---|---|---|---|---|---|
| JEVATRO1 | 2/5 | 2/5 | 平 | 296/1012 | 2339/4945 |
| JEVATRO2 | 2/5 | 2/5 | 平 | 560/652 | 3182/2395 |
| JEVATRO3 | 3/9 | 2/4 | 无Jev | 2132/651 | 16685/2211 |
| JEVATRO4 | 4/12 | **5/12** | Jev | 4560/6981 | 36711/47163 |
| JEVATRO5 | 1/3 | 1/3 | 平 | 260/260 | 1226/1226 |
| JEVATRO6 | 2/4 | 2/4 | 平 | 900/616 | 2584/2090 |
| JEVATRO7 | 4/11 | 4/11 | 平 | 2520/4494 | 28736/35378 |
| JEVATRO8 | 2/5 | **4/12** | Jev | 492/4559 | 3803/41371 |

**均值对比（有 Jev 相对无 Jev 的变化）**：

| 指标 | 无Jev | 有Jev | 变化 |
|---|---|---|---|
| 到达 Ante | 2.50 | **2.75** | **+0.25** |
| 最大单手分 | 1465 | **2403** | **+64%** |
| 全场总得分 | 11908 | **17097** | **+44%** |
| 购买数/局 | 3.75 | 5.75 | +2.00（更敢买） |
| 消耗牌使用/局 | 0 | 1.62 | +1.62（新功能） |
| 跳盲/局 | 0 | 0.38 | +0.38（Jev 独有） |
| 胜负 | — | — | Jev 胜 2 / 无Jev 胜 1 / 平 5 |

**Jev 层开销**：16 局共 132 次调用、82.5s 总延迟（0.62s/次）、约 **$0.011（≈$0.0007/局）**。

### 4. 本轮修复
- solver：极端约束叠加下合法组合为空导致 None 崩溃（JEVATRO7 实测）→ 退化前 min(5) 张兜底；
- batch_runner：单局异常不再炸整批（记录后继续）；新增 rerun_seeds.py 补跑指定种子。

### 5. 结论
消耗牌功能上线后，Jev 层在 8 种子上首次显示**全面正向**：平均 Ante +0.25、单手爆发 +64%、
总得分 +44%，成本几乎为零（分币级）。样本仍小（8 种子），JEVATRO3 一局反向（naive ante3 > jev ante2）
提示题目集仍有分桶改进空间；下一优先级是按 §8.3 流程做分桶错误率分析。


---

## 第五轮迭代（2026-09-22 凌晨）—— 开包决策 + 分桶错误率分析 + LLM 对比报告

### 1. 卡包购买与开包（Jev Choice 首次实战）
- 商店候选放行三类包：小丑包（p_buffoon，选牌入槽）/ 标准牌包（p_standard，进牌组）/
  天体包（p_celestial，星球即用）；塔罗/幻灵包开包需即时选目标，暂不买。
- 开包：`jev_layer.pack_pick` 单题 Choice（"对当前构筑最有价值的一张"），state 序列化新增
  [开包可选] 区；选不出有效答案则跳过。
- 集成测试 `test_pack.py`：买现成 Buffoon 包 → SMODS_BOOSTER_OPENED → Jev 在
  j_faceless vs j_gros_michel 中正确选出 gros_michel（+15mult）→ 入槽回商店，全链路通过。

### 2. 分桶错误率分析（`error_analysis.py`，302 次调用/24 局样本）
| 维度 | 平均分 | 平均置信度 |
|---|---|---|
| synergy | 1.64 | 0.349 |
| scaling | 2.03 | 0.265 |
| economy | 1.21 | 0.265 |
| **immediate** | **0.74** | 0.414 |

**发现**：immediate 维度均分 0.74/4 严重偏低——旧措辞"立刻缓解战力缺口(能否过关)"过苛，
Jev 几乎不给商品即时战力分 → 间接压制战力型购买。已改为"对接下来1-2个盲注得分能力的提升"
+ 更可达的 5 级描述；复测 immediate 均分 0.74→0.81。
另：方向识别 28% 未达阈值（考虑后续改 Choice 单选）；跳盲 noul 均值 0.55（阈值 0.65，平衡）。

### 3. LLM vs Jev 综合对比报告（LLM对比Jev报告.html）
口径分离：Jev 侧全部本项目实测（8种子 A/B、0.62s/次、$0.0007/局）；LLM 侧引用公开报道
（GPT-6 Astra bot 金注通关）+ 明确标注的估算（$1-10/局、5-30s/步）。
核心结论：成本差 3-4 个数量级 → 三层漏斗（求解器/Jev/LLM）是帕累托最优架构。
