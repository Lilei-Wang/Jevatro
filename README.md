# Jevatro

**An autonomous Balatro agent: an exact solver for what's computable, Jev for what needs intuition.**

[English](README.md) | [中文](README.zh-CN.md)

![Architecture](article_imgs/07_架构图.png)

Jevatro plays the real game of **Balatro** (Steam) end-to-end. It controls the game through the open-source [balatrobot](https://github.com/coder/balatrobot) mod (JSON-RPC 2.0 inside the game process), and makes every decision through a three-tier funnel:

| Tier | Decision-maker | What it owns | Cost | Latency |
|---|---|---|---|---|
| **0** | Local exhaustive **solver** | Which cards to play/discard (all ≤218 combos enumerated & scored exactly); 17 boss-blind rule constraints; consumable targeting | free, offline | ~0 |
| **1** | **[Jev](https://typesafe.ai)** — TypeSafe AI's "System One" decision model | Shop buy/sell, blind skip, archetype recognition, booster-pack picks, rerolls — batched into a single API call | $0.042/M input tokens, **output free** | ~0.6 s per batch |
| **2** | Optional **LLM arm** (any OpenAI-compatible backend, e.g. DeepSeek) | A/B comparison baseline; low-confidence escalation target | measured $0.046/game | ~6.8 s/decision |

If Jev's API fails, the bot falls back to a naive policy — a run never breaks mid-game.

## Why this split

Balatro's decisions split naturally into two kinds:

- **Exactly computable** — playing/discarding is a small combinatorial search. An LLM (or Jev) adds nothing here but cost and latency, so a local solver does it optimally for free.
- **Fuzzy judgment** — is this Joker worth $8 given my deck direction? Skip this blind? That's a calibrated-intuition task, which is exactly what Jev's Choice/Score/Noul question types are built for: atomic questions, structured answers, calibrated confidence, batched execution, output priced at zero.

Full reasoning in the technical spec ([中文](小丑牌xJev技术方案.md)) — the same "System 1 / System 2" split that motivates the model's name.

## Results (all measured, White Stake / Red Deck)

**Three-arm paired A/B** — 8 seeds × 3 configs, same game speed, per-decision JSONL logs:

| Metric (mean per game) | naive | **jev** | llm (glm-4-flash) |
|---|---|---|---|
| Ante reached | 2.62 | **2.88** | 1.88 |
| Best single hand | 1,478 | **2,475** (+68%) | 979 |
| Total score | 11,578 | **15,348** (+33%) | 3,738 |
| Purchases per game | 4.12 | **7.00** | 3.12 |
| Blind skips per game | 0 | **0.38** | 1.88 |
| Decision latency | — | **0.55 s** | 1.78 s |

![3-arm results](article_imgs/02_三配置战绩.png)

**Jev vs DeepSeek-flash** (8-seed paired):

| | **jev** | deepseek-flash |
|---|---|---|
| Avg Ante | **2.88** | 2.75 |
| Latency per decision | **0.55 s** | 6.79 s (12×) |
| API failures | **0 / 149** | ~30% (fell back to heuristics) |
| 8-game tokens | 0.30M in / **0 out** | 43K in / 116K out |
| Measured cost per game | **$0.0019** | $0.046 (~24×) |

**Honest status**: deepest run so far is **Ante 6** (a win is Ante 8). A 20-seed batch averages 2.85 Antes. The Jev layer's edge shows up first in score ceiling (+68% best hand), total output, latency, cost and zero API failures — closing the last Antes is active work (see the [execution log](EXECUTION_LOG.md), 13 iterations so far).

## Decision coverage

| Decision point | Owner | Status |
|---|---|---|
| Play / discard selection | Tier 0 solver (exact enumeration) | ✅ |
| Boss-blind constraints (The Psychic, The Eye, The Arm, … 17 types) | `rules.py` pre-filter on the solver | ✅ |
| Shop: buy / sell-to-free-slot / skip | Tier 1 Jev Composite Scoring (4-dim rubric + archetype weights) | ✅ |
| Blind skip | solver `can_clear` + Jev Noul tiebreak | ✅ |
| Consumables (Planet / Tarot / Spectral) | `use_policy.py` safety policies + shop candidates | ✅ |
| Booster packs (Buffoon / Standard / Celestial / Tarot / Spectral) | Jev Choice on card picks | ✅ |
| Shop rerolls | Jev Noul | ✅ |
| Archetype recognition (pair / flush / straight / high-card / balanced) | Jev Choice, weights shop scoring | ✅ |
| First win (Ante 8) | — | 🚧 deepest: Ante 6 |

## Repository layout

```
├── jevatro/                    # the decision engine (Python)
│   ├── client.py               #   balatrobot JSON-RPC client
│   ├── solver.py               #   Tier 0: exhaustive play/discard search
│   ├── rules.py                #   boss-blind constraint engine
│   ├── scoring.py              #   hand evaluation + ~80 joker effects
│   ├── serializer.py           #   gamestate → compact Jev state text
│   ├── card_desc.py            #   266-card effect glossary (auto-generated)
│   ├── jev_layer.py            #   Tier 1: Jev question batches
│   ├── jev_bot.py              #   solver + Jev bot
│   ├── llm_layer.py            #   Tier 2: OpenAI-compatible LLM arm
│   ├── llm_bot.py              #   solver + LLM bot
│   ├── naive_bot.py            #   baseline bot
│   ├── use_policy.py           #   consumable safety policies
│   ├── batch_runner.py         #   multi-seed paired A/B runner
│   ├── ab_report.py            #   paired A/B report
│   ├── cost_report.py          #   token/cost accounting (pricing.py)
│   ├── dashboard.py            #   local web observability UI
│   └── analyze_run.py / inspect_jev.py / error_analysis.py ...
├── 小丑牌xJev技术方案.md        # technical spec (Chinese)
├── EXECUTION_LOG.md            # full iteration log, 13 rounds (Chinese)
├── LLM对比Jev报告.html          # LLM vs Jev comparison report (Chinese)
├── 公众号文章_jevatro.md         # write-up article (Chinese)
└── article_imgs/ ui_review/    # figures & screenshots
```

## Quickstart

**Prerequisites** (Windows; the game is controlled via mods):

| Component | Version used | Where |
|---|---|---|
| Balatro (legit Steam copy) | — | `…\steamapps\common\Balatro` |
| [Lovely](https://github.com/ethangreen-dev/lovely-injector) injector | v0.9.0 | `version.dll` in the game dir |
| [Steamodded](https://github.com/Steamopollys/Steamodded) | 26.829.0 | `%AppData%\Balatro\Mods\Steamodded` |
| [balatrobot](https://github.com/coder/balatrobot) | v1.5.2 | `%AppData%\Balatro\Mods\balatrobot` (API on `127.0.0.1:12346`) |

```bash
pip install requests typesafe-sdk

# configure your key (get one at https://console.typesafe.ai)
cp jevatro/.env.example jevatro/.env    # then edit TYPESAFE_API_KEY=...

# 1. launch the game (mod auto-listens on port 12346)
start "" "D:\software\Steam\steamapps\common\Balatro\Balatro.exe"

# 2. run a bot (seed = anything)
cd jevatro
python naive_bot.py JEVATRO1     # baseline: solver + naive shop
python jev_bot.py   JEVATRO1     # solver + Jev shop/blind/pack decisions
python llm_bot.py   JEVATRO1     # solver + LLM arm (needs LLM_* in .env)

# 3. observe & analyze
python dashboard.py               # → http://127.0.0.1:8765
python analyze_run.py             # summary of the latest run
python inspect_jev.py             # per-question Jev scores & confidence
python batch_runner.py 8          # 8 seeds × 3 configs paired A/B
python ab_report.py               # paired comparison report
python cost_report.py             # token & cost accounting
```

## Observability

Every decision is logged to JSONL (solver outputs, full Jev question/answer/confidence, LLM prompts, costs). `dashboard.py` serves a dark-themed local web UI: live game screenshot + board state on the left, a live decision stream with expandable Jev/LLM Q&A on the right.

![Dashboard](article_imgs/10_观测台.png)

## Documentation (Chinese)

- [小丑牌xJev技术方案](小丑牌xJev技术方案.md) — the 12-chapter technical spec: architecture, question-set design, evaluation matrix, roadmap
- [EXECUTION_LOG.md](EXECUTION_LOG.md) — every iteration: what was tried, what broke, what was measured, what got reverted
- [LLM对比Jev报告](LLM对比Jev报告.html) — Jev vs LLM comparison with measured costs
- [公众号文章](公众号文章_jevatro.md) — the narrative write-up

## Acknowledgments

- [balatrobot](https://github.com/coder/balatrobot) (orig. [beaston](https://github.com/beaston/balatrobot), maintained by coder) — the in-game JSON-RPC API this project is built on
- [Evalatro](https://github.com/alesha-pro/evalatro), [balatro-gym](https://github.com/cassiusfive/balatro-gym), [balatro-calculator](https://github.com/EFHIII/balatro-calculator) — prior art studied in the spec
- [Lovely](https://github.com/ethangreen-dev/lovely-injector) & [Steamodded](https://github.com/Steamopollys/Steamodded) — the modding stack
- [TypeSafe AI](https://typesafe.ai) — the Jev / System One decision model

## Disclaimer

Balatro is a single-player game by LocalThunk/Playstack. This project is a personal AI experiment: it requires a legitimately owned Steam copy, touches no game files beyond the standard community mod stack, and is not affiliated with or endorsed by the developer. The mod ecosystem it builds on is long-tolerated by the game's creator.
