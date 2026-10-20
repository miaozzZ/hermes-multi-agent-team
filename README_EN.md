# 🚀 hermes-multi-agent-team

**Build your AI Agent team in 10 minutes — Multi-agent collaboration automation for [Hermes Agent](https://github.com/NousResearch/hermes-agent)**

> 🇨🇳 [中文版](README.md) | 🇬🇧 English

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Hermes Agent](https://img.shields.io/badge/Hermes-Agent-green.svg)](https://github.com/NousResearch/hermes-agent)
[![CI](https://github.com/bagoetadrich/hermes-multi-agent-team/actions/workflows/ci.yml/badge.svg)](https://github.com/bagoetadrich/hermes-multi-agent-team/actions/workflows/ci.yml)

---

## 🤔 What is this?

`hermes-multi-agent-team` is a CLI tool that automates the setup of a multi-agent collaboration team powered by [Hermes Agent](https://github.com/NousResearch/hermes-agent), with real-time collaboration through messaging platforms (Feishu/Lark, Telegram, Discord, Slack).

**Setting up a 6-agent team manually requires:**
- Creating 6 platform apps/bots
- Configuring 6 Hermes Profiles
- Writing 6 SOUL.md personas
- Handling 20+ known pitfalls (open_id isolation, bot-to-bot communication, event subscriptions...)
- 2+ hours of debugging

**With this tool:**
```bash
hermes-team init --team-name MyTeam --roles pm,fe,be,qa,ui
hermes-team configure --prefix MyTeam
hermes-team start --prefix MyTeam
hermes-team collect-ids --prefix MyTeam
hermes-team verify --prefix MyTeam
```

10 minutes. Done ✅

---

## 🎯 Project Positioning

`hermes-multi-agent-team` is a **CLI tool + Hermes Skill** combo:

| Usage | Description | Best for |
|-------|-------------|----------|
| **Standalone CLI** | Run `hermes-team` commands directly | Scripting, CI/CD, fine-grained control |
| **Hermes Skill** | Tell Hermes "help me build a team" and it runs the CLI automatically | Natural language interaction, agent autonomy |

---

## 📐 Architecture

```
Messaging Platform (Feishu / Telegram / Discord / Slack)
├── 🧠 Coordinator (Hub)  ← Task decomposition, assignment, consolidation
├── 📋 PM                  ← PRD, user stories, requirements
├── 💻 Frontend Dev        ← Vue/React/CSS
├── 🔧 Backend Dev         ← API/Database/Architecture
├── 🧪 QA                  ← Test cases, bug reports
├── 🎨 UI Designer         ← Interface design, interaction specs
└── 👤 You                 ← Give requirements, make decisions
```

Each Agent = **Independent Hermes Profile** + **Independent Bot App** + **Independent SOUL.md persona**

### 🔄 Hub-and-Spoke Collaboration Model

This project uses a **Hub-and-Spoke** collaboration architecture:

- **Hub**: The Coordinator Agent is the central node — task decomposition, assignment, and consolidation
- **Spokes**: Each specialized Agent (PM, Frontend, Backend, QA, Designer) communicates only with the Hub
- **You**: Issue instructions through the Coordinator, view consolidated results

**Why Hub-and-Spoke?**
1. **No communication chaos** — Agents don't talk directly to each other, preventing task conflicts
2. **Clear role boundaries** — Each Agent focuses only on their domain
3. **Single coordination point** — Coordinator tracks global progress
4. **Easy to extend** — New roles only need to register with the Coordinator

**Example workflow:**
```
You:          "@Coordinator We need a login feature"
Coordinator:  "@PM Please write the PRD"
PM:           "@Coordinator PRD done, see doc link"
Coordinator:  "@Frontend @Backend Implement per PRD"
Frontend:     "@Coordinator Frontend done"
Backend:      "@Coordinator Backend done"
Coordinator:  "@QA Please test"
QA:           "@Coordinator Tests passed"
Coordinator:  "@You Feature complete ✅"
```

### 🎯 Role Responsibilities

| Role | Core Responsibility | Output |
|------|-------------------|--------|
| 🧠 Coordinator | Task decomposition, assignment, tracking | Task board, progress reports |
| 📋 PM | Requirements analysis, PRD writing | PRD docs, user stories |
| 💻 Frontend | UI implementation, interaction logic | Vue/React components, styles |
| 🔧 Backend | API design, database, business logic | API interfaces, DB design |
| 🧪 QA | Test cases, bug reports, quality assurance | Test reports, bug lists |
| 🎨 Designer | Interface design, interaction specs | Design mockups, specs |

---

## 🌐 Supported Platforms

> ⚠️ **Automation currently covers Feishu only**: `configure` writes `FEISHU_*` keys and `start` validates Feishu credentials. The other platforms below are supported by Hermes itself but require **manual** `.env` editing per profile, and cannot pass `hermes-team start` credential validation.

| Platform | Status | Config Fields |
|----------|--------|--------------|
| **Feishu / Lark** | ✅ Full support (tool-automated) | `FEISHU_APP_ID`, `FEISHU_APP_SECRET` |
| **Telegram** | ⚠️ Supported by Hermes, manual setup | `TELEGRAM_BOT_TOKEN` |
| **Discord** | ⚠️ Supported by Hermes, manual setup | `DISCORD_BOT_TOKEN`, `DISCORD_APP_ID` |
| **Slack** | ⚠️ Supported by Hermes, manual setup | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |

---

## 📦 Installation

```bash
# Install from source
git clone https://github.com/bagoetadrich/hermes-multi-agent-team.git
cd hermes-multi-agent-team
pip install -e .

# Ensure Hermes Agent is installed
hermes --version
```

**Prerequisites:**
- Python 3.10+
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) **>= 0.19** (multiplexed gateway: one host gateway serves all profiles; run `hermes-team doctor` to check)
- A messaging platform account — each agent needs its **own** Feishu app/bot

---

## 🎯 Quick Start

### Step 1: Create Platform Bots (manual)

Create a bot/app on your messaging platform for each role:

**Feishu/Lark:**
- [Feishu Open Platform](https://open.feishu.cn/) → Create app → Enable Bot capability
- Permissions: `im:message`, `im:message:send_as_bot`, `im:resource`, `im:chat:readonly`
- ⚠️ Key permission: `im:message.group_at_msg.include_bot:readonly`

**Telegram:**
- Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → Get token

**Discord:**
- [Discord Developer Portal](https://discord.com/developers/applications) → Create app → Add Bot

### Step 2: Initialize Team

```bash
hermes-team init --team-name MyTeam --roles pm,fe,be,qa,ui
```

### Step 3: Configure Credentials

```bash
hermes-team configure --prefix MyTeam
```

⚠️ **Each agent must use its own Feishu app** — one app_id can only serve one Hermes instance; the tool enforces uniqueness across profiles. Shared settings (domain, policies) are asked once.

### Step 4: Start Gateways

```bash
hermes-team start --prefix MyTeam
```

Starts the host multiplex gateway (one process serving all profiles, the default since Hermes 0.19). Credentials are validated first in both modes: every profile needs its own `FEISHU_APP_ID`/`FEISHU_APP_SECRET`, and App IDs must be unique across **all host-served profiles under `profiles/`** (other teams included; parked/standalone profiles skipped) plus the default profile's `~/.hermes/.env`. Use `--standalone` for the legacy one-gateway-per-profile mode.

### Step 5: Collect IDs

```bash
hermes-team collect-ids --prefix MyTeam
```

### Step 6: Verify

```bash
hermes-team verify --prefix MyTeam
```

---

## 📋 Commands

| Command | Description |
|---------|-------------|
| `hermes-team init` | Create profiles + generate SOUL.md templates |
| `hermes-team configure` | Interactively configure .env for each profile |
| `hermes-team start` | Start the host multiplex gateway serving all profiles |
| `hermes-team collect-ids` | Auto-extract platform IDs from gateway logs |
| `hermes-team verify` | Verify all configurations are correct |
| `hermes-team status` | Show team status overview |
| `hermes-team doctor` | Diagnose environment dependencies |
| `hermes-team destroy` | Clean up team profiles |

Run `hermes-team <command> --help` for detailed options.

---

## 🎨 Custom Roles

Create custom roles by adding templates:

```
hermes_multi_agent_team/templates/
├── SOUL/
│   ├── coordinator.md.j2    # Coordinator
│   ├── pm.md.j2             # Product Manager
│   ├── frontend.md.j2       # Frontend Dev
│   ├── backend.md.j2        # Backend Dev
│   ├── qa.md.j2             # QA
│   └── designer.md.j2       # UI Designer
├── env.j2                   # .env template
└── config.yaml.j2           # config.yaml template
```

Jinja2 variables:
- `{{ name }}` — Display name
- `{{ nickname }}` — Nickname
- `{{ role }}` — Role title
- `{{ team_name }}` — Team name
- `{{ team_members }}` — Team member list

---

## 🛠️ Development

```bash
git clone https://github.com/bagoetadrich/hermes-multi-agent-team.git
cd hermes-multi-agent-team
pip install -e ".[dev]"
pytest
ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## 📖 Case Study

- [BaGoet Team](examples/baogoet-team/) — A 6-agent multi-role collaboration team

---

## 🤝 Contributing

PRs welcome! Especially interested in:

- 🌍 More platform adapters
- 🎭 More role templates (DevOps, Data Analyst, Content Creator...)
- 🖥️ Web UI management interface
- 📦 Preset team templates (Customer Service, Content Team...)

---

## 📄 License

MIT License — see [LICENSE](LICENSE)

---

## 🙏 Acknowledgements

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — Underlying AI Agent framework
- [Feishu Open Platform](https://open.feishu.cn/) — Messaging collaboration platform
- BaGoet Team — The first real-world verified multi-agent team
