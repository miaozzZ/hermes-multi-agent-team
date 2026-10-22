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

`hermes-multi-agent-team` 是一个 **独立 CLI 工具**：`hermes-team init / configure / start / ...` 直接运行，不依赖 Hermes Agent 运行时，适合脚本化、CI/CD 与手动精细控制。

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
  --team-name TEXT    团队名称（命令行或 --config 文件二选一提供）
  --roles TEXT        角色列表，逗号分隔；缺省 = 全部角色
  --prefix TEXT       Profile 名称前缀（默认使用 team-name）
  --clone-from TEXT   从已有 Profile 克隆模型配置
  --config PATH       团队配置 JSON：自定义角色/名称/模板（见下节）
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

# 使用自定义团队配置
hermes-team init --config my-team.json
```

**重跑行为：**
- 渲染名单 = 本次 `--roles` 选中的角色 ∪ 磁盘上仍活跃的团队成员（`add-member` 加入的成员、旧版无元数据 profile——后者按 profile 后缀识别）：子集重跑不会把未选中的成员从 SOUL 名单里挤掉，输出会提示 `Including N on-disk member(s) ...`；on-disk 成员与配置角色重名时报错（名字必须全局唯一，collect-ids 按名匹配）
- 磁盘上残留的 coordinator profile（元数据 `coordinator=true`）按总管对待、优先于配置里的 render-only hub（与 add-member 的名单重建优先级一致），不会被当成普通成员渲染
- `remove-member --keep-profile` 移除的成员不会被复活：重跑 init 跳过该 profile 并提示（被移除的 coordinator 同样宣告跳过，不再显示"将创建"）

### `hermes-team configure`

交互式配置每个 Profile 的 `.env` 文件。

```bash
hermes-team configure [OPTIONS]

Options:
  --prefix TEXT      Profile 名称前缀  [required]
  --dry-run          显示将要写入的内容，不实际写入
```

行为说明：
- 每个角色单独输入 **Feishu App ID / App Secret**，工具强制查重（一个 app_id 只能服务一个 Hermes 实例）；终端上 Secret 逐字符回显 `*`，支持退格（方向键等转义序列被忽略），凭证输入自动去除首尾空白（含全角空格）；管道/CI 仍走隐藏输入
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

为每个 profile 的 SOUL.md 回填 open_id（按 profile 独立、幂等）。

```bash
hermes-team collect-ids [OPTIONS]

Options:
  --prefix TEXT    Profile 名称前缀  [required]
  --via-api        用每个 profile 自己的 App 凭证读群历史（推荐点名制团队使用）
  --chat-id TEXT   群 chat_id（oc_xxx），仅与 --via-api 搭配（单独使用报用法错误）；
                   缺省取各 profile 日志里最新的群聊 chat_id
                   （无群聊行时才退回任意会话；非法值直接报用法错误）
```

**命名空间规则（正确性核心）**：open_id 只在观察到它的 App 里有效，所以每个 profile 的 SOUL **只**用它自己观测到的 id 回填——绝不跨 profile 合并。

**四个数据来源**（优先级 api > mention > sender > log，见各 profile 报告的 sources 分布）：
- `--via-api`：用该 profile 的 App 凭证换 token 调飞书 API 读**群消息历史**，从结构化 mentions 数组提取（完整不截断、无需发新消息）。缺 `im:message.group_msg` 权限时会打印该 App 的一键授权链接；顺带用群信息接口补齐 `@主人` 的 open_id（该接口缺权限时只跳过 `@主人`，已取到的 mentions 不受影响）。API 域名跟随 profile 的 `FEISHU_DOMAIN`（lark 团队走 open.larksuite.com）
- **mention 日志**：点名制（`FEISHU_REQUIRE_MENTION=true`，省 token 推荐模式）下入站日志的 `[Mentioned: 名字 (open_id=ou_xxx)]` 条目——名字逐字保留（括号后缀是命名的一部分、名字里的逗号也不会截断）、接收方自身被剔除、120 字符截断的残缺条目自动跳过
- **sender 日志**：自由模式下该 profile 日志里的 `sender=bot:ou_xxx`（自己的 id，自己的命名空间）
- **主人日志**：入站元数据行里的 `sender=user:ou_xxx` 回填 `@主人`（仅当日志中只观测到**唯一一个**真人 id 时；出现多个真人时无法判定谁是主人，跳过并提示改用 `--via-api` 或手填）。消息正文里出现的 chat_id/sender 不会被当作元数据

**幂等**：只替换 `ou_xxx` 占位符，已手工回填/已收集的真实 id 永不改写，重跑安全。每个 profile 如实报告：填了几个、还剩几个占位符、来源分布（"还剩几个"与 `verify` 同口径——`@主人` 与渲染用总管的占位符按设计豁免，不计入缺口）。

### `hermes-team add-member`

向已有团队增加一个成员，并同步所有成员的 SOUL 名单。

```bash
hermes-team add-member [OPTIONS]

Options:
  --prefix TEXT     团队前缀  [required]
  --key TEXT        角色 key（profile 名为 <prefix>-<key>）  [required]
  --name TEXT       显示名（SOUL @标签用，须全团队唯一）  [required]
  --role TEXT       职位  [required]
  --nickname TEXT   小名（默认同 --name）
  --template TEXT   SOUL 模板：文件路径或内置短名；缺省用 --key 对应的内置模板
  --clone-from TEXT 从已有 Profile 克隆模型配置
  --dry-run         只显示将要做的变更
```

**行为：**
- 从各 profile 的 `.hermes-team.json` 元数据重建团队名单（旧版无元数据团队自动回退内置角色表 + M总 占位）
- **先收获**所有 SOUL 里已回填的真实 open_id，重建后再回灌——加人不会把已收集的 open_id 重置成占位符
- 新成员的 SOUL 用完整名单渲染（队友的真实 open_id 直接带入）；存量成员的 SOUL 按其元数据记录的模板重渲染
- 只对【飞书@方式】小节做补丁式更新、不整体重渲染的两种情况：① 旧版无元数据（legacy）成员——原团队名只存在于其 SOUL 文本中，重渲染会把团队名错改成 prefix（新成员的团队名会从现有 SOUL 中提取复用，提取不到才回退 prefix）；② 自定义模板文件已不存在——不覆盖手写人设

**加人后：** `configure`（新成员要自己的飞书 App）→ 拉进群 → 等 ~30s host 重扫 → `collect-ids`（回填新成员 open_id）。

### `hermes-team remove-member`

从团队移除一个成员，并同步其余成员的 SOUL 名单。

```bash
hermes-team remove-member [OPTIONS]

Options:
  --prefix TEXT   团队前缀  [required]
  --key TEXT      要移除成员的角色 key  [required]
  --keep-profile  保留 Hermes profile（只从团队名单和 SOUL 中移除）
  --force         跳过确认
  --dry-run       只显示将要做的变更
```

**行为：**
- 默认**删除**该成员的 profile 目录并写入 tombstone（`profiles/.deleted/<name>`，与 Hermes 自身的删除语义一致）；`--keep-profile` 只把它从名单移除
- 其余成员的 SOUL 重渲染为不含该成员的名单，已收集的 open_id 保留
- 移除的是总管（coordinator）时会明确警告：剩余成员的 SOUL 将不再有总管条目
- 不能移除团队最后一个成员（用 `destroy`）
- 飞书侧需要手动把机器人移出群

### `hermes-team new-bot`

创建**独立单功能 agent**——不属于任何团队，由 host 网关直接服务。

```bash
hermes-team new-bot NAME [OPTIONS]

Options:
  --display-name TEXT  人设显示名（默认同 NAME）
  --description TEXT   一句话功能描述（缺省时交互询问；--dry-run 用占位符，不询问）
  --template TEXT      SOUL 模板：文件路径或内置 roster-free `bot` 模板（默认）。内置团队模板（pm/frontend/coordinator…）依赖名单上下文，会被拒绝并提示
  --clone-from TEXT    从已有 Profile 克隆模型配置
  --dry-run            只显示将要做的变更
```

**适用场景**：签到、播报、查询这类单职责 bot。它们与团队的差别：

- SOUL 是无名单的简洁模板（没有【飞书@方式】、没有协作规则）；`verify` 对它跳过 open_id 检查
- 元数据标记 `standalone: true`：`collect-ids`、团队增减成员、`init` 重跑的成员并集扫描都会**自动忽略**它（即使它与某团队共享前缀）；`destroy` 也**不会**删除共享前缀的 standalone bot
- 配置/凭证与其他 profile 一致：`configure --prefix NAME`（要自己的飞书 App），`start` 的查重同样覆盖它
- 单功能 bot 通常希望**只被 @ 时响应**：`configure` 时把 `REQUIRE_MENTION` 保持默认 `true`（与团队成员相反；团队+bot 共享前缀的混合 configure 中，该键会为 bot 单独再问一次，默认仍为 `true`）
- 不进群的用法（cron/CLI）：建好后直接 `hermes -p NAME chat` 或挂 cron，无需任何飞书配置

### `hermes-team new-config`

交互式向导，生成团队配置 JSON（配合 `init --config` 使用）。

```bash
hermes-team new-config [OUTPUT_PATH]
```

流程：团队名称 → 前缀（路径安全校验）→ 总管安排三选一（独立 profile / 主 profile 担任 render-only / 无）→ 角色名单（从内置 5 角色逐个取舍，再添加自定义角色；与已选角色 key/名称冲突的内置角色自动跳过）→ 预览并写出。key/名称非法或重复时立即重问该项（其余错误重填该角色）；写出前先用与 `init --config` 相同的加载器在临时文件上回环验证，通过后才原子替换目标文件。

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

检查环境依赖与就绪状态。**不接收任何参数**——它检查的是运行环境，不是某个团队的配置（团队层面的检查由 `verify --prefix` 负责）。

```bash
hermes-team doctor
```

检查项（`doctor.py` 的 7 项环境检查）：
- 🔍 Python ≥ 3.10
- 🔍 Hermes CLI 可用（含 `~/.hermes/hermes-agent/venv/bin/hermes` 安装位）
- 🔍 Hermes 版本 ≥ 0.19（multiplexed gateway；过低时提示 `hermes update`）
- 🔍 Python 依赖：click、python-dotenv、Jinja2
- 🔍 `~/.hermes/profiles` 目录是否存在

存在失败检查项时以**非 0 退出码**结束（脚本/CI 可感知）。

### `hermes-team destroy`

清理团队：删除团队 Profile 目录（不停止 Gateway——multiplex host 网关会继续运行，重扫后不再服务被删除的 profile）。共享该前缀的 **standalone bot 不会被删除**（`--force` 也不删，会提示手动清理路径）。

```bash
hermes-team destroy [OPTIONS]

Options:
  --prefix TEXT    Profile 名称前缀  [required]
  --force          跳过确认提示
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

角色和名称通过**团队配置 JSON** 外置定义，不需要改代码。写一个 `my-team.json`：

> 💡 不想手写 JSON？运行 `hermes-team new-config`（或 `hermes-team new-config 路径.json`）：向导逐项提问、边填边校验（非法 key / 重名会立即重问），总管安排三选一（独立 profile / 主 profile 担任 / 无），从内置 5 角色逐个取舍、再添加自定义角色，最后写出**保证可加载**的配置文件并提示下一步命令。

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

```bash
hermes-team init --config my-team.json
```

字段说明：
- `team_name` / `prefix`：可选默认值，命令行参数优先
- `roles`：每个角色需要 `key`（进入 profile 名 `<prefix>-<key>`，限字母/数字/`-`/`_`）、`name`（SOUL 与 collect-ids 回填 open_id 的匹配名，**必须全局唯一**）、`role`（职位）；`nickname` 缺省等于 `name`
- `coordinator`：可选。声明后 init 会**一并创建总管 profile** 并渲染总管 SOUL（不声明则沿用旧行为：不建总管 profile，总管由你的主 profile 担任）
- `coordinator_fallback`：可选，与 `coordinator` **互斥**（两者同时声明会在加载时报错）。声明一个 **render-only 总管条目**（`name` 必填；`role` 缺省 `总管`，`nickname` 缺省 `name`）：只进入 `team_members` 供成员 @（内置模板要求「只 @总管 汇报」），不建 profile（其占位符 open_id 与普通成员一样，collect-ids **观测到该名字时自动回填**；未观测到时与主人行一样豁免缺口统计，verify 不因此失败）；名称须与角色名互异。内置默认团队自带的这一条目为 `M总`
- `template`：自定义角色必须指定。可以是相对 config 文件的**模板文件路径**（完全自定义人设；只相对 config 所在目录解析，不回退当前目录），也可以复用内置模板的短名（`pm`/`frontend`/`backend`/`qa`/`designer`/`coordinator`/`bot`——`bot` 为无【飞书@方式】的简洁模板，团队渲染时以 `role` 文本充当 `description`、身份句自称该团队的单职责成员，`verify` 对它跳过 open_id 检查）；内置 5 角色（pm/fe/be/qa/ui）不写则用默认模板

init 会在每个 profile 里写入 `.hermes-team.json` 元数据，`collect-ids` 据此适配自定义角色名（**声明 coordinator 时**总管的 open_id 也自动回填），旧团队（无元数据）自动回退到内置角色表；`verify` 对占位符 open_id 的识别按 `ou_xxx` 前缀、天然适配任意角色名，它只读元数据的 standalone 标记与模板名（standalone bot 与 roster-free `bot` 模板成员跳过 open_id 名单检查）。注意：**声明了 `coordinator_fallback` 的团队（以及内置默认团队）**才有 render-only 总管占位（无 profile/元数据），其 open_id 会在 collect-ids **观测到时自动回填**（群历史/日志提及即填；未观测到的占位符豁免缺口统计，需要时也可手动填写）；两者都未声明的自定义团队 roster 中没有任何总管条目。

自定义 SOUL 模板是 Jinja2，可用变量：
- `{{ name }}` / `{{ nickname }}` / `{{ role }}` — 本角色的显示名/小名/职位
- `{{ description }}` — 一句话描述（roster-free `bot` 模板使用；团队渲染等于 `role` 文本，`new-bot` 为功能描述）
- `{{ team_name }}` — 团队名称
- `{{ team_members }}` — 团队成员列表（`name`/`nickname`/`role`/`open_id`），声明 coordinator 时总管排第一；不声明时若声明了 `coordinator_fallback`（或内置默认团队自带的 `M总`）则该 render-only 总管条目排第一，否则只含声明的角色（注意：内置模板要求成员「只 @总管 汇报」，建议声明 `coordinator` 或 `coordinator_fallback`，否则成员没有可 @ 的总管条目，init 也会给出警告）
- `{{ owner_open_id }}` — 主人 open_id 占位

> 提示：人设正文使用 `{% for member in team_members %}` 循环生成 `<at user_id="{{ member.open_id }}">...</at>` 标签，collect-ids 就能自动回填 open_id。回填只认 `<at>` 标签、**不要求固定的小节标题**——内置模板的 `【飞书@方式】` 小节即满足，自定义标题（如 `【飞书@格式】`）同样有效。

内置模板位于 `hermes_multi_agent_team/templates/SOUL/`（coordinator/pm/frontend/backend/qa/designer/bot），可直接复制一份改写。

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
