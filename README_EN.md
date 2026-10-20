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
| `hermes-team add-member` | Add a member to an existing team (syncs every SOUL roster, preserves collected open_ids) |
| `hermes-team remove-member` | Remove a member (deletes their profile unless --keep-profile, syncs SOULs) |
| `hermes-team verify` | Verify all configurations are correct |
| `hermes-team status` | Show team status overview |
| `hermes-team doctor` | Diagnose environment dependencies |
| `hermes-team destroy` | Clean up team profiles |

Run `hermes-team <command> --help` for detailed options.

---

## 🎨 Custom Roles

Roles and names are externalized to a **team config JSON** — no code changes needed. Write a `my-team.json`:

```json
{
  "team_name": "ContentTeam",
  "prefix": "content",
  "roles": [
    {"key": "writer", "name": "阿写", "nickname": "写写", "role": "内容创作",
     "template": "souls/writer.md.j2"},
    {"key": "ops", "name": "老运", "role": "运维", "template": "backend"}
  ],
  "coordinator": {"key": "boss", "name": "老板", "role": "总管", "template": "coordinator"}
}
```

Then run `hermes-team init --config my-team.json`.

Field notes:
- `team_name` / `prefix`: optional defaults; CLI flags win
- `roles`: each needs `key` (part of the profile name `<prefix>-<key>`, letters/digits/`-`/`_`), `name` (matched by collect-ids when filling open_ids — **must be unique**) and `role` (job title); `nickname` defaults to `name`
- `coordinator`: optional — when declared, init also **creates the coordinator's profile** and renders the coordinator SOUL (without it, keep using your main profile as the hub, as before)
- `coordinator_fallback`: optional and **mutually exclusive** with `coordinator` (declaring both is a load-time error). Declares a **render-only hub entry** (`name` required; `role` defaults to 总管, `nickname` to `name`): it only joins `team_members` so members have a hub to @ (bundled templates say "report to the hub only") — no profile is created and its open_id is not auto-filled; its name must differ from every role name. The builtin default team ships one named `M总`
- `template`: required for custom keys — either a file path relative to the config file's directory (fully custom persona; resolved against the config directory only, never the cwd) or a builtin short name (`pm`/`frontend`/`backend`/`qa`/`designer`/`coordinator`); the builtin five roles default to their bundled templates

`init` writes a `.hermes-team.json` metadata file into every profile; `collect-ids` uses it to adapt to custom role names (the coordinator's open_id is auto-filled too, **when a coordinator is declared**), and legacy teams without metadata fall back to the builtin role table. `verify` does not read the metadata — it detects placeholder open_ids by their `ou_xxx` prefix, so it works with any role names. Note: only teams that declare `coordinator_fallback` (and the builtin default team) carry a render-only hub placeholder (no profile/metadata) — its open_id is **not** auto-filled; set it by hand if needed. A custom config declaring neither has no hub entry in the roster at all.

Custom SOUL templates are Jinja2 with: `{{ name }}` / `{{ nickname }}` / `{{ role }}`, `{{ team_name }}`, `{{ team_members }}` and `{{ owner_open_id }}`. `team_members` entries carry `name`/`nickname`/`role`/`open_id`, with the declared coordinator first; without one, a `coordinator_fallback` entry (or the builtin default team's legacy `M总`) leads the roster — otherwise custom configs list exactly their declared roles (note: bundled templates tell members to report to the hub only, so declare `coordinator` or `coordinator_fallback` unless you use fully custom templates — init warns about a missing hub). Keep the `【飞书@方式】` section with a `{% for member in team_members %}` loop of `<at user_id="{{ member.open_id }}">…</at>` so collect-ids can fill the ids. Bundled templates live in `hermes_multi_agent_team/templates/SOUL/` — copy one to start from.

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
