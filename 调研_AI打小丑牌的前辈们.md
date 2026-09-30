# 调研：AI 打小丑牌的"前辈们"——文章"前辈探路"段落事实核查与增补

> 调研日期：2026-09-30 ｜ 对象：公众号文章第二节"前辈探路"段落的三个说法
> 结论先行：**三个说法全部有实锤来源，但其中一个（RL 胜率）已过时**——2026 年 6 月出现了新方案。

## 一、逐条核查

### 说法 1："有人用 GPT-6 级的大模型接上游戏控制接口，真打穿了最高难度金注黑牌组" ✅ 准确

- **原始出处**：Reddit r/balatro 帖 [My Balatro Bot just won at Gold Stake Black Deck](https://www.reddit.com/r/balatro/comments/1wboqlj/my_balatro_bot_just_won_at_gold_stake_black_deck/)
- **媒体报道**：[Tom's Hardware：AI enthusiast builds GPT-6 Astra-powered bot...](https://www.tomshardware.com/tech-industry/artificial-intelligence/ai-enthusiast-builds-gpt-6-astra-powered-bot-to-take-on-balatros-gold-stake-black-deck-bot-leverages-python-for-numerical-tools-beats-hardest-difficulty-repeatedly)（另有 [Digg 转载](https://digg.com/tech/grn7bh82)）
- **可核实细节**：GPT-6 Astra 驱动；**Python 数值工具管算分**（与本项目的 solver 分层一致，验证了三层架构的方向）；**多次**通关金注黑牌组（"beats hardest difficulty repeatedly"，非偶然一局）
- **文章里的推论性表述**（"每步 5-30 秒、成本以美元计、照样犯低级错误"）：媒体帖未给出精确延迟/成本数字，属合理量级推断（GPT-6 级旗舰推理 + 每步 LLM 决策）。**建议文章保持现状（已标注估算口径）或弱化为"每步以十秒计、成本以美元计"**。

### 说法 2："强化学习路线的训练成果停在白注两成胜率上下" ⚠️ 曾准确，2026-06 起过时

- **历史依据**：果蝇脑项目与 PPO 端到端基线均在 ~20% 一档（见说法 3）；西班牙拉古纳大学 2025 年本科论文 [Inteligencia Artificial aplicada a Balatro](https://riull.ull.es) 也是"复杂规则下训练 RL agent"的早期尝试
- **重要更新——[Taming Balatro: Pushing White Stake Clear Rate to 99%](https://styleofwong.cn)（2026-06-28）**：
  - 结论：**端到端 PPO 走不通**（与本文章判断一致），采用 **MCTS + RL 混合架构**将白注 Ante 8 通关率目标推到 **99%**；
  - 内容含机制建模/状态动作空间设计/奖励塑形/算法选型，作者称"可落地技术蓝图"；
  - 局限：全文约千字、面向白注；更高注级未见数据
- **对文章的影响**：建议将该句改为"纯端到端强化学习曾长期停在白注两成胜率上下（2026 年中出现 MCTS+RL 混合方案才把白注通关率推向 99%，但更高难度仍无公开数据）"——既保留原论点（RL 样本效率困境是真的）又不失准确。

### 说法 3："有人拿谷歌的果蝇脑模拟来训，胜率也就 20%" ✅ 准确（注意口径）

- **原始出处**：Reddit 帖（PC Gamer 2026-09 报道），标题即"**Balatro fan claims they trained Google fruit fly brain simulation to beat the game — reinforcement learning currently has the model at 20% success rate**"
- **背景**：Google/Janelia 完成果蝇全脑连接组测绘后，社区用其仿真玩 DOOM/Mario 64/Beat Saber（[daily.dev 汇总](https://daily.dev)），本项目把同样的"模拟感官输入 + 多巴胺式强化"套到小丑牌上
- **口径注意**：20% 是**发帖人自述**，非同行评审；且是"进行中的训练成果"而非上限。文章现有表述"胜率也就 20%"可保留，若求严谨可加"（发帖人自述口径）"。

## 二、增补发现：前辈生态比文章写的更热闹

调研中发现的同生态项目（文章若想扩充"前辈"段落可用）：

| 项目 | 路线 | 关键事实 | 来源 |
|---|---|---|---|
| **Ballad**（polina4096/Ballad） | LLM 直接决策（Anthropic 兼容 API） | gamestate 以 JSON 喂给模型；作者结论：**即使带 extended thinking 的更强模型也难以通关**——长视野规划对 LLM 仍难 | [GitHub](https://github.com/polina4096/Ballad)、[balatrobot issue #153](https://github.com/coder/balatrobot/issues/153) |
| **r/ArtificialInteligence 帖** | LLM + JSON 状态 | "LLMs can beat Balatro"，称胜率可比肩人类玩家（社区对状态字符串化方式有争议） | Reddit 转述 |
| **BalatroLLM / BalatroBench**（coder/） | LLM bot + **基准排行榜** | 基于 balatrobot API 的自主对局 + 跨模型横评榜单 | balatrobot 社区 |
| **Taming Balatro** | MCTS+RL 混合 | 白注 99% 蓝图；证实纯 PPO 不可行 | [styleofwong.cn](https://styleofwong.cn) |
| **GPT-6 Astra bot** | 旗舰 LLM + Python 算分工具 | 金注黑牌组多次通关（本项目引用的同一案例） | Tom's Hardware |

**生态层面的洞察**（可供文章结尾或"该怎么用"一节引用）：LLM 直驱（Ballad）打不过、旗舰+工具（GPT-6 bot）能通关但贵、MCTS+RL 便宜但只到白注——**恰好没有人占据"亚秒级、近零成本、结构化"的判断模型生态位，这正是 Jevatro 的立身之处**，也反过来强化文章的"三层漏斗"论点。

## 三、给文章的修订建议（未动文章，仅建议）

1. **必改**：RL 胜率句补 2026-06 更新（99% MCTS+RL），否则与最新公开事实不符；
2. **可选**：在"前辈"段加一句 Ballad 的"extended thinking 也难通关"——它是"纯 LLM 不行"的最直接证据；
3. **可选**：结尾方法论处可引 BalatroBench——本项目可直接提交榜单成为横向对照。
