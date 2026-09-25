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


---

## 第六轮迭代（2026-09-22 上午）—— 规则小丑建模 + 方向Choice化 + 环境瓶颈攻坚

### 1. 代码改进（全部提交，单测通过）
- **规则改变型小丑求解支持**：j_splash（全牌计分）/ j_four_fingers（4张成花顺）/
  j_shortcut（顺子允许1间隔）此前按 0 效果计导致错估，现完整建模（rule_flags 贯穿评估与计分）。
- **方向识别 Choice 化**：5 连 Noul（28% 未达阈值）→ 单题 Choice（pair/flush/straight/highcard/balanced），
  econ 方向退役（交给 economy 维度）。
- **sanity 实测（迭代前半段，机器空闲时）**：JEVATRO1 从 ante2 → **ante5 r13**（该种子历史最好），
  卖牌腾位首次实战 ×2、塔罗/兑换券/方向切换全激活。

### 2. 环境瓶颈发现（重要结论：批量对局需要机器空闲）
20 种子批量触发连锁问题，完整诊断链：
1. `play` 60s ReadTimeout → requests 异常逃逸（已修：网络异常归一化 + 状态对比恢复）；
2. 游戏服务器假死 → 后续局全灭（已修：gamestate_retry + SystemExit 捕获）；
3. 游戏画面冻结检测（已修：连续8轮状态签名不变 → 放弃该局 + 自动重启游戏自愈）；
4. **根因锁定**：Balatro 在后台被 Windows 严重节流——游戏帧循环极慢（每手牌动画 ~2 分钟），
   `G.buttons` 因 STATE_COMPLETE 迟迟不达而长期为 nil，表现为"冻结"。
   证据：screenshot 显示画面正常渲染；menu 调用秒回且画面切换成功（游戏活着）；
   高优先级 + 强制出牌补丁后对局能推进但每步仍 ~2 分钟。
5. 对策已内置：mod 强制出牌补丁（G.buttons 缺失时直接高亮并调用游戏函数）+
   批量器冻结自愈；**但根本解法是批跑时保持机器空闲/游戏前台**（昨晚批量全速 ~2分钟/局）。

### 3. 待执行
- 20 种子大样本 A/B 代码全部就绪（`python batch_runner.py 20`，含自愈），
  需在机器空闲时段执行（预计 1.5-2 小时全速）。


---

## 第七轮迭代（2026-09-22 下午）—— 传统 LLM 决策层实测 + 三配置 24 局对比

### 1. LLM 决策层（`llm_layer.py` / `llm_bot.py`）
- 用户提供智谱 API key；实测账号仅 **glm-4-flash** 可用（其余模型 1113 余额不足，
  充值后改 `.env` 的 `ZHIPU_MODEL=glm-5` 即可复测旗舰）。
- 与 JevLayer 同接口镜像（商店/盲注/开包），JSON 容错解析，失败回退 naive；
  token 与延迟全记录（kind="llm"）；每 ante 最多跳 1 盲护栏（实测连跳 2 盲直冲 Boss 必败）。

### 2. 游戏提速三件套（解决昨天的"环境瓶颈"）
- **G.SETTINGS.GAMESPEED=4**（balatrobot start 端点 mod 补丁，三臂等速不影响公平）；
- **窗口置顶角落 + 高优先级**（boost_game.ps1）——真正根因找到了：LÖVE 的 update/draw
  串行，窗口被完全遮挡时 vsync 阻塞 draw → 整个游戏循环停摆（昨天的"冻结"）；
- 批量器自愈重启后自动重挂置顶。
- 效果：批量回到全速（每局 ~2 分钟），24 局 70 分钟跑完。

### 3. 三配置 24 局同种子成对实测（种子 JEVATRO1-8，红牌组白注）
| 指标（均值/局） | naive | jev | llm(glm-4-flash) |
|---|---|---|---|
| 到达 Ante | 2.62 | **2.88** | 1.88 |
| 最大单手分 | 1478 | **2475** | 979 |
| 全场总得分 | 11578 | **15348** | 3738 |
| 购买数 | 4.12 | **7.00** | 3.12 |
| 跳盲数 | 0 | 0.38 | 1.88 |
| 最深局数（并列计胜） | 6 | 6 | 3 |
| 决策延迟/次 | - | **0.55s** | 1.78s |
| 决策成本/局 | - | **$0.0007** | ¥0（免费档） |

**结论**：Jev 全指标第一；glm-4-flash（免费小模型）三臂垫底——购买保守、跳盲激进、
JSON 偶发截断。旗舰 LLM 上限（公开：GPT-6 bot 金注通关）需充值实测。

### 4. 修复与工具
- ab_report.py：三配置成对解析（曾把 llm 局误归入 naive 桶）+ LLM 开销统计；
- batch_runner.py：三配置 + 自愈重启后重挂窗口置顶；
- hunt_win.py：冲关狩猎（找首胜触发无限模式）。

### 5. 无限模式
- bot 循环只认 GAME_OVER，胜利后自动继续（无限模式支持就绪）；
  当前三臂白注最深 ante 4-5，尚未通关，无限模式上限数据待决策层强化后产出。


---

## 第八轮迭代（2026-09-22 傍晚）—— LLM 臂切换 DeepSeek + Jev 优势专项对比

### 1. DeepSeek 对接
- 按官方文档（OpenAI 兼容）：base `https://api.deepseek.com`，模型 `deepseek-flash`；
- 实测特性：thinking 默认开启（内容在 content、思考在 reasoning_content），
  关闭 thinking 反而输出损坏（`<|TOOL_CALL|>` 混入）；max_tokens 400→2000（思考吃配额）；
- llm_layer 改为通用后端配置（LLM_BASE/LLM_API_KEY/LLM_MODEL，兼容旧 ZHIPU_*）；
- 修复：游戏双实例冲突（端口打架）→ 单实例重启。

### 2. Jev vs DeepSeek-flash（8 种子成对，jev/naive 用同版本最新数据）
| 指标 | naive | jev | deepseek-flash |
|---|---|---|---|
| 平均 Ante | 2.62 | **2.88** | 2.75 |
| 最大单手分 | 1478 | **2475** | 2162 |
| 总得分 | 11578 | **15348** | 14629 |
| 最深局数 | 4 | **5** | 4 |
| 决策延迟/次 | - | **0.55s** | 6.79s（12倍） |
| 8局 tokens | - | 0.30M in / 0 out | 43K in / **116K out** |
| 调用失败 | - | **0/149** | ~30%（回退启发式） |

**Jev 五大优势**（已写入报告 §4.5）：快12倍/零失败/输出免费且结构化/批量并行/战绩第一且更稳。
**DeepSeek 反向证据**（诚实记录）：JEVATRO3（Jev 失误局）反超到 ante4、JEVATRO8 达 ante5
（全场最深）——思考型残局推理是真实优势，Tier 2 定位依据。


---

## 第九轮迭代（2026-09-22 晚）—— Agent Lab 观测台（参考 Jev Tetris 风格）

- dashboard.py 全面重写为深色 observability 风格（参考用户提供的 Jev Tetris 界面）：
  - 左栏 01 PLAYGROUND：实时游戏截图（balatrobot screenshot 代理，3s 缓存）+
    实时局面（gamestate 代理：Ante/轮/金币/chips 需求比/盲注效果）+
    手牌可视化（花色着色 + 修饰标记）+ 小丑列表；
  - 右栏 02 DECISION STREAM · LIVE：统计条（动作数/Jev+LLM 调用/平均耗时/tokens）+
    决策流卡片（ACTION/JEV/LLM/失败/终局分色标签，点击展开请求原文与回答，
    Jev 卡含每题答案+置信度条，LLM 卡含 PROMPT/REPLY，一键复制）；
  - 顶栏：109 局历史下拉（含进行中标记）+ 跟随最新 + balatrobot 连接状态灯；
  - 浏览器实测 + 视觉模型评估通过（可发布 MVP 质量）。


### 迭代 8.1（同日晚）—— 修正与再验证

**迭代 8 复盘（重要方法论教训）**：
- 16 新种子（17-32）实测：均值 Ante 2.06、**死时金币 $6**（此前深局是 $46）——
  "超息全局降阈值购买"是**净负面**：钱砸在 0.30-0.40 的平庸小丑上，经济耗尽战力没起来；
- **修正**：撤回 rich→0.30 全局放宽（保留早期小丑<3 的 0.32、卖牌 0.50、
  重掷放宽、经济/X倍率两类 state 警示）；
- 方法论：死因分析指出的问题（囤钱）是真的，但解药要指向"确定性升级"（星球/好塔罗/X倍率）
  而非"泛买便宜货"——每个策略改动都要同种子复测，不能只看单局。

**迭代 8.1 验证（种子 1-8 复测）**：
- 结果 [2,2,2,1,2,**6**,4,2]，均值 2.62（与迭代 7 的 2.88 在 Jev 随机波动范围内）；
- **JEVATRO6 打到 Ante 6——全项目新纪录**（该种子历史最好仅 2），离通关（Ante 8）只差两轮；
- 无首胜。Jev 决策非确定性（同策略同种子两次可差 ±1 ante），8 局样本不足以区分 8.1 与 7，
  需 20+ 种子大样本才有结论。


---

## 第十轮迭代（2026-09-22 深夜）—— Token/成本全链路记账（Jev vs DeepSeek）

**需求**：记录每次 Jev 与 DeepSeek 调用的 token 消耗与成本对比，价格取官方线上价。

**官方价格查证（2026-09-22）**：
- Jev (TypeSafe System One)：输入 $0.042/百万 tokens，输出免费；
- deepseek-flash (V4.1-Flash)：输入未命中 $0.30 / 命中 $0.006、输出 $1.20
  （USD/百万，高峰价；非高峰一律半价）。

**实现**：
- 新增 pricing.py 中央价格表（含来源 URL+查价日期）与成本函数；
- Jev 层：SDK 响应自带 usage（实测 in/out tokens）+ model，逐次落盘 cost_usd；
- LLM 层：补记 DeepSeek 缓存命中/未命中拆分（prompt_cache_hit/miss_tokens），
  逐次落盘 cost_usd（默认高峰价=保守上界）；
- 新增 cost_report.py：扫描全部历史日志，产出 logs/cost_report.md
  （价格表 / 总消耗对比 / 逐局明细 / 单次调用口径四节）；
- ab_report.md 开销章节改为实测 token+成本（Jev 旧日志按文本长度估算，
  估算系数由 COST9 局 27 次实测校准：中文状态文本 ≈ 0.93 字符/token）；
- LLM对比Jev报告.html §4/§4.5/§8 同步官方价+实测数据，
  修正旧结论"DeepSeek 便宜到可忽略"→ 实测单局成本 Jev 约为 LLM 的 1/18。

**COST9 三配置验证局（全实测口径）**：
- naive Ante 4（172s，0 模型调用）；jev Ante 3（154s，27 调用 0 失败，
  实测 45,415 in / 5,029 out，$0.0019/局）；llm Ante 4（356s，24 调用 9 回退，
  11,129 in / 35,367 out 思考，$0.046/局）；
- 历史累计（截至本轮）：Jev 1082 调用 $0.074；LLM 201 调用 $0.204；
- 诚实记录：9 种子后三臂 Ante 均值在噪声内（naive 2.78/jev 2.67/llm 2.89），
  Jev 的稳定优势在单手分上限/总得分/延迟/成本/零失败。


---

## 第十一轮迭代（2026-09-25）—— 魔典审计驱动的决策盲点修复

**审计方法**：外部 wiki 直连被网络拦截，改用三方对照——balatrobot API 全表（21 个方法）、
本地 266 张卡魔典数据（card_desc）、决策代码。结论：4 高影响 + 5 中影响盲点。

**本轮实施（6 项）**：
1. 钢牌/金牌弃牌保留（高）：best_discard 现在永不弃钢牌（在手 ×1.5 倍率）、
   优先保留金牌（每回合 +$3），单测通过；
2. 解禁塔罗包/幻灵包（高）：BUYABLE_PACK_PREFIXES 加入 p_tarot/p_spectral，
   开包选卡由 pack_pick 承接（NO_BUY 卡不进候选且保留原始下标映射）；
3. 消耗牌槽满先用腾位（高）：SHOP 分支开头若满员先 apply(max_uses=1) 用掉安全可用品；
4. 星球牌型守卫（中）：PLANET_HAND 映射 + _arch_hint（历史最多打法）——
   只买升级主力方向或已打≥2次牌型的星球；
5. Boss 预告行 + 标签价值标注（中）：局面文本加"⚠Boss预告: 名字: 效果"，
   跳盲奖励标签附高/较高/一般/低价值分级（wiki 通用战略原则）；
6. 标准包卡组约束（中）：卡组 ≥60 张后不再买标准牌包（防稀释抽牌质量）。

**明确不做的两项（及理由）**：
- 经济性卖牌（卖烂仔回血凑利息）：迭代 8 教训——放宽花钱方向的改动必须极谨慎，
  留待大样本验证钢牌/包解禁收益后再议；
- rearrange 小丑重排序：静态近似算分不建模触发顺序，收益无法归因，记为远期。

**回归（同种子 A/B，基线=接力赛 Jev 臂战绩）**：
- 种子 DEMOV42/44/48/50/58/74：新代码 [5,4,4,4,5,4] vs 基线 [5,4,4,4,5,4]，**6/6 持平**；
- 首跑暴露 solver.py 缺 mods 导入（NameError），修复后全绿；
- 行为变化可验证：塔罗购买/使用显著增多（力天使/力量/魔术师/星辰等），
  星球购买全部匹配主力方向，非法动作保持 0；
- 诚实结论：本批是"正确性/机会面"修复，这些种子上没有即时分差——
  钢牌保留只在出钢牌的局生效，包类解禁收益需深局/大样本体现。
