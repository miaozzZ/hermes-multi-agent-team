# Changelog

## [0.4.0] - 2026-10-20

### 🔄 适配 Hermes >= 0.19 multiplexed gateway（破坏性变更）

Hermes 自 0.19 起默认使用 multiplexed gateway：**单个 host 网关进程服务所有 profile**，对具名 profile 执行 `gateway install/start` 会被拒绝（exit 78）。本版本将工具从「每 profile 一个网关进程」迁移到新架构。

**`hermes-team start` 重写：**
- 🌐 默认启动 host multiplex 网关（一次 `hermes gateway install/start`，服务全部 profile）
- ✅ 启动前校验每个 profile 的 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` 齐全，且 **App ID 不重复**（共享 app_id 会被网关拒绝/park）
- 🕰️ 检测到 Hermes < 0.19 时自动回退旧的 per-profile 模式；`--standalone` 可强制旧模式
- 💨 dry-run 同步支持

**`hermes-team configure` 对齐现行 Hermes 飞书渠道：**
- ❌ 移除已废弃变量：`FEISHU_DM_POLICY`（`FEISHU_ALLOW_ALL_USERS` 仍被 Hermes 0.22.x 读取与写入，重配时原样保留，不再视为废弃）
- ➕ 新增 `FEISHU_GROUP_POLICY`（默认 `open`；Hermes 默认 allowlist 且空名单会拒收所有群消息）
- ⚠️ **移除「所有 profile 共用一个飞书 App」选项**——现行 Hermes 一个 app_id 只允许一个实例；现在每个角色必须输入独立的 App ID/Secret，重复会被要求重输
- 🔄 公共设置（域名/连接模式/群策略等）默认只询问一次，应用到全部 profile；`FEISHU_ALLOWED_USERS` 因 open_id per-app 隔离改为**按 profile 单独询问**，不再跨 profile 共享
- 🛡️ 写入 `.env` 时保留工具不管理的键（如模型 API Key），不再整文件覆盖；dry-run 回显对疑似敏感键（`SECRET`/`KEY`/`TOKEN`/`PASSWORD`/`ENCRYPT`）一律打码
- 🔒 重配时已有 App Secret 不再作为 prompt 默认值回显在终端（`show_default=False`），且新 Secret 不允许留空

**其他：**
- 🩺 `doctor` 新增 Hermes 版本检查（< 0.19 提示 `hermes update`）；存在失败检查时以非 0 退出码结束
- ✅ `verify` 新增团队级重复 App ID 检查与「allowlist + 空名单」检查；recommended 键列表对齐新 schema；存在失败检查时以非 0 退出码结束（脚本/CI 可感知）
- 📡 `verify`/`status` 的网关状态识别感知 multiplex 架构：被 host 网关服务（`gateway_state.json` 的 `served_profiles`）的 profile 不再误报 "not running"
- 🚀 `start` 的 `hermes gateway status` 调用不再因超时/二进制缺失抛未捕获异常（install/start 已成功时仅跳过状态打印）；`--standalone` 模式同样执行凭证校验；App ID 查重覆盖 `profiles/` 下**所有**被 host 服务的 profile（含其他 team，跳过 parked/standalone）及默认 profile 的 `~/.hermes/.env`，`verify` 的团队级查重同口径
- 🔍 `hermes --version` 解析要求退出码为 0 且优先匹配带 hermes/v 前缀的版本号，避免把 stderr 里的无关数字当成版本
- 📚 README 修正 `configure --platform` 文档漂移（CLI 从未有过该参数），补充 multiplex 说明与两个新已知坑（GROUP_POLICY 默认值、卡片回调 tab）；平台表注明工具自动化仅覆盖飞书

## [0.3.0] - 2026-05-29

### 🔧 工程化与健壮性

**新增功能：**
- 🩺 `hermes-team doctor` 命令 — 诊断配置问题，支持 `--fix` 自动修复
- 💥 `hermes-team destroy` 命令 — 清理团队（停止 Gateway、删除 Profile）
- 📄 `CONTRIBUTING.md` — 贡献指南，包含开发环境搭建和 PR 流程

**模板更新：**
- 📐 所有 SOUL.md 模板新增 Hub-and-Spoke 协作模式说明
- 🎯 明确成员间不互相 @、一切通过总管协调的协作规则

**工程化：**
- 🧪 新增测试套件（pytest），覆盖核心命令逻辑
- 🔄 新增 GitHub Actions CI（lint + test on push/PR）
- 📦 修复 `templates` 目录未被打包进 wheel/sdist 的问题

**文档：**
- 📚 README 新增「项目定位」章节（CLI 工具 + Hermes Skill 双模式）
- 📚 README 命令列表补充 `doctor`、`destroy`
- 📚 CHANGELOG 记录本轮工程化改进

## [0.2.0] - 2026-05-29

### 🔄 架构升级：Hub-and-Spoke 协作模式

**新增功能：**
- 📐 **Hub-and-Spoke 协作架构**：明确总管作为中心节点的协调模式
- 🎯 **Skill 定位描述**：每个角色的核心职责和产出物定义
- 📚 **README 更新**：新增协作模式说明和角色职责表

**改进：**
- ✅ 优化团队协作流程，避免 Agent 间直接通信
- ✅ 强化角色边界，每个 Agent 专注自己的专业领域
- ✅ 完善文档，提升新用户理解效率

**文档更新：**
- README 新增「Hub-and-Spoke 协作模式」章节
- README 新增「Skill 定位（角色职责）」章节
- CHANGELOG 记录本轮架构升级

## [0.1.0] - 2026-05-29

### 🎉 Initial Release

**核心功能：**
- `hermes-team init` — 一键创建 Hermes profiles + 生成 SOUL.md 人设模板
- `hermes-team configure` — 交互式配置飞书 App 凭证
- `hermes-team start` — 批量启动所有 gateway
- `hermes-team collect-ids` — 自动从 gateway 日志提取 per-app open_id
- `hermes-team verify` — 全面验证团队配置是否正确
- `hermes-team status` — 团队状态一览

**支持的角色模板：**
- 总管/协调员 (coordinator)
- 产品经理 (pm)
- 前端开发 (frontend)
- 后端开发 (backend)
- 测试QA (qa)
- UI设计 (designer)

**自动处理的已知问题：**
- ✅ 飞书 open_id per-app 隔离
- ✅ bot-to-bot 通信配置 (FEISHU_ALLOW_BOTS, FEISHU_REQUIRE_MENTION)
- ✅ 事件订阅范围检查
- ✅ SOUL.md 中 @mention 格式校验
- ✅ .env 凭证配置
