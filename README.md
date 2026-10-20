# 🚀 hermes-multi-agent-team

**10 分钟搭建你的 AI Agent 团队 —— Hermes + 多平台多 Agent 协作自动化工具**

> 🇨🇳 中文 | 🇬🇧 [English](README_EN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Hermes Agent](https://img.shields.io/badge/Hermes-Agent-green.svg)](https://github.com/NousResearch/hermes-agent)
[![CI](https://github.com/bagoetadrich/hermes-multi-agent-team/actions/workflows/ci.yml/badge.svg)](https://github.com/bagoetadrich/hermes-multi-agent-team/actions/workflows/ci.yml)

---

## 🤔 这是什么？

`hermes-multi-agent-team` 是一个 CLI 工具，自动化搭建基于 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的多 Agent 协作团队，通过消息平台（飞书、Telegram、Discord、Slack）实现 Agent 之间的实时协作。

**手动搭建一个 6 人 Agent 团队需要：**
- 创建 6 个飞书应用
- 配置 6 个 Hermes Profile
- 编写 6 份 SOUL.md 人设
- 处理 20+ 个已知坑（open_id 隔离、bot-to-bot 通信、事件订阅...）
- 调试 2+ 小时

**用这个工具：**
```bash
hermes-team init --team-name MyTeam --roles pm,fe,be,qa,ui
hermes-team configure --prefix MyTeam
hermes-team start --prefix MyTeam
# 飞书群里 @所有人 → 等 30 秒
hermes-team collect-ids --prefix MyTeam
hermes-team verify --prefix MyTeam
```

10 分钟搞定 ✅

---

## 🎯 项目定位

`hermes-multi-agent-team` 是一个 **CLI 工具 + Hermes Skill** 的组合：

| 使用方式 | 说明 | 适用场景 |
|----------|------|----------|
| **独立 CLI** | 直接运行 `hermes-team` 命令 | 脚本化、CI/CD、手动精细控制 |
| **Hermes Skill** | 对 Hermes 说「帮我搭团队」，它按 Skill 指导自动调用 CLI | 自然语言交互、Agent 自主操作 |

- **CLI 工具**：`hermes-team init / configure / start / ...`，可独立使用，不依赖 Hermes Agent 运行时
- **Hermes Skill**：`multi-agent-team-setup` Skill 文件，安装到 Hermes 后，Agent 会自动理解如何搭建和管理团队
- 两者共享同一套核心代码，Skill 是 CLI 的「使用说明书」

---

## 📐 架构

```
消息平台（飞书 / Telegram / Discord / Slack）
├── 🧠 总管 (Coordinator)  ← 任务拆解、分配、汇总
├── 📋 产品经理 (PM)       ← PRD、需求、用户故事
├── 💻 前端开发 (Frontend)  ← Vue/React/CSS
├── 🔧 后端开发 (Backend)   ← API/数据库/架构
├── 🧪 测试QA (QA)         ← 测试用例、Bug报告
├── 🎨 UI设计 (Designer)   ← 界面设计、交互规范
└── 👤 主人 (You)           ← 提需求、做决策
```

每个 Agent = **独立 Hermes Profile** + **独立平台 Bot** + **独立 SOUL.md 人设**

### 🌐 支持的平台

> ⚠️ **本工具的自动化目前仅覆盖飞书**：`configure` 只写入 `FEISHU_*` 配置项，`start` 也只校验飞书凭证。
> 下表中的其他平台由 Hermes 本身支持，但需要**手动**编辑各 profile 的 `.env`，且无法通过 `hermes-team start` 的凭证校验。

| 平台 | 状态 | 配置项 |
|------|------|--------|
| **飞书 / Lark** | ✅ 完整支持（工具自动化） | `FEISHU_APP_ID`, `FEISHU_APP_SECRET` |
| **Telegram** | ⚠️ Hermes 支持，需手动配置 | `TELEGRAM_BOT_TOKEN` |
| **Discord** | ⚠️ Hermes 支持，需手动配置 | `DISCORD_BOT_TOKEN`, `DISCORD_APP_ID` |
| **Slack** | ⚠️ Hermes 支持，需手动配置 | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |

### 🔄 Hub-and-Spoke 协作模式

本项目采用 **Hub-and-Spoke（星型）协作架构**：

- **中心节点（Hub）**：总管 Agent（M总）负责任务拆解、分配和汇总
- **外围节点（Spoke）**：各专业 Agent（PM、前端、后端、测试、设计）只与中心节点通信
- **主人（You）**：通过总管下达指令，查看汇总结果

**为什么选择 Hub-and-Spoke？**
1. **避免通信混乱**：Agent 之间不直接对话，防止任务冲突和重复工作
2. **清晰的职责边界**：每个 Agent 只关注自己的专业领域
3. **单一协调点**：总管掌握全局进度，确保任务有序执行
4. **易于扩展**：新增角色只需向总管注册，无需修改其他 Agent

**协作流程示例：**
```
主人: "@M总 我们需要一个用户登录功能"
M总: "@P酱 请写 PRD"
P酱: "@M总 PRD 已完成，见文档链接"
M总: "@F仔 @B叔 根据 PRD 开发"
F仔: "@M总 前端完成"
B叔: "@M总 后端完成"
M总: "@Q宝 请测试"
Q宝: "@M总 测试通过"
M总: "@主人 功能已完成 ✅"
```

### 🎯 Skill 定位（角色职责）

每个 Agent 都有明确的 **Skill 定位**，定义在其 SOUL.md 中：

| 角色 | 核心职责 | 主要产出 |
|------|----------|----------|
| 🧠 总管 (M总) | 任务拆解、分配、进度跟踪、汇总 | 任务分配表、进度报告 |
| 📋 产品经理 (P酱) | 需求分析、PRD 撰写、用户故事拆解 | PRD 文档、用户故事 |
| 💻 前端开发 (F仔) | UI 实现、交互逻辑、前端架构 | Vue/React 组件、样式 |
| 🔧 后端开发 (B叔) | API 设计、数据库、业务逻辑 | API 接口、数据库设计 |
| 🧪 测试QA (Q宝) | 测试用例、Bug 报告、质量保证 | 测试报告、Bug 列表 |
| 🎨 UI设计 (U酱) | 界面设计、交互规范、设计系统 | 设计稿、交互规范 |

**Skill 边界原则：**
- 每个 Agent **只做自己领域的事**（P酱不写代码，F仔不做测试）
- 遇到跨领域问题 → **上报总管协调**，不自行处理
- 产出物必须**可验证**（文档有链接，代码有测试，设计有规范）

---

## 📦 安装

```bash
# 从源码安装
git clone https://github.com/bagoetadrich/hermes-multi-agent-team.git
cd hermes-multi-agent-team
pip install -e .

# 确保 Hermes Agent 已安装
hermes --version
```

**前置要求：**
- Python 3.10+
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) **>= 0.19**（multiplexed gateway：单 host 网关服务所有 profile；运行 `hermes-team doctor` 检查版本）
- 消息平台账号（每个 Agent 需要一个**独立**的飞书 App/Bot）

---

## 🎯 快速开始

### Step 1: 创建平台 Bot（手动）

在你的消息平台上为每个角色创建一个 Bot：

**飞书/Lark：**
- [飞书开放平台](https://open.feishu.cn/) → 创建应用 → 启用机器人能力
- 权限：`im:message`, `im:message:send_as_bot`, `im:resource`, `im:chat:readonly`
- ⚠️ 关键权限：`im:message.group_at_msg.include_bot:readonly`

**Telegram：**
- 找 [@BotFather](https://t.me/BotFather) → `/newbot` → 获取 Token

**Discord：**
- [Discord Developer Portal](https://discord.com/developers/applications) → 创建应用 → 添加 Bot

**Slack：**
- [Slack API](https://api.slack.com/apps) → 创建 App → 添加 Bot

### Step 2: 初始化团队

```bash
hermes-team init --team-name MyTeam --roles pm,fe,be,qa,ui
```

这会：
- 创建 5 个 Hermes Profile（`MyTeam-pm`, `MyTeam-fe`, ...）
- 为每个角色生成对应的 SOUL.md 人设模板

### Step 3: 配置平台凭证

```bash
hermes-team configure --prefix MyTeam
```

⚠️ **每个 Agent 必须使用独立的飞书 App**（一个 app_id 只能服务一个 Hermes 实例，共享凭证会被网关拒绝/park）。工具会为每个角色单独询问 App ID/Secret 并强制查重；域名、群策略等公共设置只需回答一次（`FEISHU_ALLOWED_USERS` 因 open_id per-app 隔离而按角色单独询问）。

### Step 4: 启动 Gateway

```bash
hermes-team start --prefix MyTeam
```

启动 host multiplex 网关（单进程服务所有 profile，Hermes >= 0.19 默认行为）。启动前会校验每个 profile 的凭证齐全且 App ID 不重复——查重覆盖 `profiles/` 下所有被 host 服务的 profile（含其他 team）、默认 profile 的 `~/.hermes/.env` 也参与。如需旧版「每 profile 一个网关进程」模式，用 `--standalone`（凭证校验同样生效；Hermes >= 0.19 下还需在 profile 的 config.yaml 里设置 `gateway.standalone: true`）。

### Step 5: 收集 open_id

1. 在飞书群里 @所有机器人
2. 等待 30 秒
3. 运行：

```bash
hermes-team collect-ids --prefix MyTeam
```

自动从 Gateway 日志中提取每个 Agent 视角的 open_id 并更新 SOUL.md。

### Step 6: 验证

```bash
hermes-team verify --prefix MyTeam
```

检查所有配置是否正确。

---

## 📋 命令详解

### `hermes-team init`

创建 Hermes Profiles 并生成 SOUL.md 模板。

```bash
hermes-team init [OPTIONS]

Options:
  --team-name TEXT    团队名称  [required]
  --roles TEXT        角色列表，逗号分隔 (pm,fe,be,qa,ui)  [default: pm,fe,be,qa,ui]
  --prefix TEXT       Profile 名称前缀（默认使用 team-name）
  --clone-from TEXT   从已有 Profile 克隆模型配置
  --dry-run           显示将要执行的操作，不实际执行
```

**示例：**
```bash
# 使用默认 5 个角色
hermes-team init --team-name BaGoet --prefix baoget

# 只创建 PM 和前端
hermes-team init --team-name MyTeam --roles pm,fe

# 从已有 profile 克隆模型配置
hermes-team init --team-name MyTeam --clone-from my-base-profile
```

### `hermes-team configure`

交互式配置每个 Profile 的 `.env` 文件。

```bash
hermes-team configure [OPTIONS]

Options:
  --prefix TEXT      Profile 名称前缀  [required]
  --dry-run          显示将要写入的内容，不实际写入
```

行为说明：
- 每个角色单独输入 **Feishu App ID / App Secret**，工具强制查重（一个 app_id 只能服务一个 Hermes 实例）
- 域名、连接模式、群策略（`FEISHU_GROUP_POLICY`）、允许的机器人等公共设置默认只询问一次、应用到全部 profile
- `FEISHU_ALLOWED_USERS` 例外：open_id 是 **per-app 隔离**的，无法跨 profile 共用，因此对每个角色单独询问（若群策略选了 `allowlist` 而名单留空，该 bot 会拒收所有群消息，工具会给出警告）
- 写入 `.env` 时会**保留**工具不管理的键（如模型 API Key），并清理已废弃的变量（`FEISHU_DM_POLICY`；`FEISHU_ALLOW_ALL_USERS` 仍被 Hermes 0.22.x 读取，会原样保留）

### `hermes-team start`

启动服务所有 profile 的 host multiplex 网关。

```bash
hermes-team start [OPTIONS]

Options:
  --prefix TEXT    Profile 名称前缀  [required]
  --standalone     旧模式：为每个 profile 单独启动网关（Hermes >= 0.19 默认拒绝，需在 profile config.yaml 设置 gateway.standalone: true）
  --dry-run        显示将要执行的命令，不实际执行
```

启动前会校验：每个 profile 的 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` 齐全，且 App ID 不重复。查重范围为 **`profiles/` 下所有被 host 网关服务的 profile**（含其他 team 的 profile；已 park 或 `gateway.standalone` 的 profile 除外）以及默认 profile 的 `~/.hermes/.env`——multiplex 与 `--standalone` 模式均校验。校验失败时退出码为非 0，可直接用于脚本/CI 判断。

**multiplex 模式下的日常操作：**
```bash
hermes gateway restart              # 修改 .env 后立即生效（平时 ~30s 自动重扫）
hermes -p MyTeam-pm gateway stop    # 单独停用一个角色（park），不影响其他人
hermes gateway status               # 查看 host 网关状态
```

### `hermes-team collect-ids`

从 Gateway 日志自动提取 per-app open_id 并更新 SOUL.md。

```bash
hermes-team collect-ids [OPTIONS]

Options:
  --prefix TEXT    Profile 名称前缀  [required]
```

**原理：**
- 读取每个 Profile 的 `logs/gateway.log`
- 正则匹配 `sender=bot:ou_xxx` 和 `sender=user:ou_xxx`
- 自动更新 SOUL.md 中 `【飞书@方式】` 的 open_id

### `hermes-team verify`

全面验证团队配置。

```bash
hermes-team verify [OPTIONS]

Options:
  --prefix TEXT    Profile 名称前缀  [required]
```

检查项：
- ✅ Profile 目录存在
- ✅ .env 包含必需字段
- ✅ 群策略合理性（`allowlist` 且名单为空会拒收所有群消息）
- ✅ SOUL.md 存在且有 @mention 格式
- ✅ open_id 已填充（非占位符）
- ✅ Gateway 运行中（multiplex 模式下由 host 网关服务的 profile 也能正确识别）
- ✅ 飞书连接正常
- ✅ 团队级：App ID 不重复（一个 app_id 只能服务一个 Hermes 实例）

任何检查失败时命令以**非 0 退出码**结束，可直接用于脚本/CI 判断。

### `hermes-team status`

显示团队状态概览。

```bash
hermes-team status [OPTIONS]

Options:
  --prefix TEXT    Profile 名称前缀  [required]
```

### `hermes-team doctor`

诊断团队配置问题并给出修复建议。

```bash
hermes-team doctor [OPTIONS]

Options:
  --prefix TEXT    Profile 名称前缀  [required]
  --fix            自动修复可修复的问题
```

检查项：
- 🔍 Profile 目录结构完整性
- 🔍 `.env` 字段缺失或格式错误
- 🔍 SOUL.md 中 open_id 是否为占位符
- 🔍 Gateway 进程是否存活
- 🔍 模板文件是否为最新版本
- 🔍 `--fix` 模式可自动修复常见问题

### `hermes-team destroy`

清理团队：停止 Gateway、删除 Profile 目录。

```bash
hermes-team destroy [OPTIONS]

Options:
  --prefix TEXT    Profile 名称前缀  [required]
  --dry-run        显示将要删除的内容，不实际执行
  --keep-logs      保留日志文件
```

⚠️ **注意：** 此操作不可逆，请确保已备份重要数据。

---

## ⚠️ 已知问题与解决方案

### 1. open_id 是 per-app 隔离的

**问题：** 同一个人/机器人，在不同飞书 App 下的 open_id **完全不同**。

**解决：** 每个 Agent 的 SOUL.md 必须使用**自己 App 视角**的 open_id。`collect-ids` 命令自动处理这个问题。

### 2. `<at>` 标签在文本消息中是纯文本

**问题：** 飞书 API 发送 `msg_type="text"` 时，`<at user_id="ou_xxx">名字</at>` 不会生成真正的 @mention。

**解决：** 设置 `FEISHU_REQUIRE_MENTION=false`，让 bot 响应所有群消息而非仅响应 @mention。

### 3. 事件订阅必须选「接收群中所有消息」

**问题：** 如果选「仅接收@机器人的消息」，bot 收不到其他 bot 的消息。

**解决：** 在飞书开发者后台 → 事件与回调 → `im.message.receive_v1` → 选择「接收群中所有消息」。

### 4. `.env` 写入被 secret redaction 破坏

**问题：** Hermes 工具系统会自动脱敏 API key，导致写入 `.env` 的内容被替换为 `***`。

**解决：** `configure` 命令直接操作文件系统，绕过 Hermes 工具层。

### 5. 配对审批后 bot 仍拒绝用户

**问题：** `hermes pairing approve` 写入的审批文件不够，还需要 `.env` 中的 `FEISHU_ALLOWED_USERS`。

**解决：** `configure` 命令自动设置所有必需的 `.env` 字段。

### 6. `FEISHU_GROUP_POLICY` 默认是 allowlist，空名单会拒收所有群消息

**问题：** Hermes 现行默认 `FEISHU_GROUP_POLICY=allowlist`，且 allowlist 为空时**所有群消息都会被拒**（私聊不受影响），群聊表现为全员沉默。

**解决：** `configure` 命令默认写入 `FEISHU_GROUP_POLICY=open`；若选 `allowlist`，务必同时填写 `FEISHU_ALLOWED_USERS`。

### 7. 卡片按钮回调要配在「回调配置」tab

**问题：** `card.action.trigger` 如果加在「事件订阅」tab，点击卡片按钮会报错 200340/220340，事件根本不会到达 Hermes。

**解决：** 在飞书开发者后台 → 回调配置（订阅方式选长连接）→ 添加 `card.action.trigger` → 开启交互卡片 → 发布新版本。

---

## 🎨 自定义角色

你可以修改模板文件来创建自定义角色：

```bash
# 模板位置
hermes_multi_agent_team/templates/
├── SOUL/
│   ├── coordinator.md.j2    # 总管
│   ├── pm.md.j2             # 产品经理
│   ├── frontend.md.j2       # 前端开发
│   ├── backend.md.j2        # 后端开发
│   ├── qa.md.j2             # 测试QA
│   └── designer.md.j2       # UI设计
├── env.j2                   # .env 模板
└── config.yaml.j2           # config.yaml 模板
```

Jinja2 变量：
- `{{ name }}` — 显示名称
- `{{ nickname }}` — 小名
- `{{ role }}` — 角色标题
- `{{ team_name }}` — 团队名称
- `{{ team_members }}` — 团队成员列表

---

## 🛠️ 开发

```bash
# 克隆仓库
git clone https://github.com/bagoetadrich/hermes-multi-agent-team.git
cd hermes-multi-agent-team

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码检查
ruff check .
```

---

## 📖 实战案例

- [BaGoet 团队](examples/baogoet-team/) — 6 个 Agent 的多角色协作团队实例

---

## 🤝 贡献

欢迎 PR！特别期待：

- 🌍 支持更多平台（Telegram、Discord、Slack）
- 🎭 更多角色模板（DevOps、数据分析、内容创作...）
- 🖥️ Web UI 管理界面
- 📦 预设团队模板（客服团队、内容团队...）

---

## 📄 License

MIT License — 详见 [LICENSE](LICENSE)

---

## 🙏 致谢

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — 底层 AI Agent 框架
- [飞书开放平台](https://open.feishu.cn/) — 消息协作平台
- [Telegram Bot API](https://core.telegram.org/bots/api) — Telegram 机器人平台
- [Discord Developer Portal](https://discord.com/developers) — Discord 机器人平台
- BaGoet 团队 — 第一个实战验证的多 Agent 团队
