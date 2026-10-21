# Changelog

## [0.8.0] - 2026-10-21

### 🤖 独立单功能 agent 成为一等公民（new-bot）

不需要团队的单职责 bot（签到/播报/查询…）有了专门入口：

- ➕ `hermes-team new-bot NAME [--display-name] [--description] [--template] [--clone-from] [--dry-run]`：创建独立 profile（名字即 profile 名，无前缀拼接）+ 渲染**无名单**的简洁 SOUL + 写入 `standalone: true` 元数据
- 📄 新增内置 `bot` 模板（职责/响应规则/风格，无【飞书@方式】），`bot` 同时注册为模板短名（团队配置也能用；团队渲染上下文以 role 文本充当 `description` 插槽，身份句按 `team_name` 分支——团队渲染自称该团队专注单一职责的成员，standalone 渲染仍说"不属于任何团队"）。`--template` 接受文件路径或内置 `bot` 短名；**内置团队模板（pm/frontend/coordinator…）会被拒绝**——它们渲染名单与 @方式 小节，独立 bot 没有对应上下文（此前会静默渲染出空插值的残缺 SOUL）；自定义模板以严格未定义变量模式渲染，引用 `team_members` 等团队变量会显式报错而非渲染为空
- 🔌 host 网关本来就服务一切 profile——新 bot 建好即被收编（~30s 重扫）；要进群则 `configure --prefix NAME`（要自己的飞书 App）
- 🎛️ `configure` 感知 standalone：单功能 bot 的 `FEISHU_REQUIRE_MENTION` 默认翻转为 **true**（只被 @ 时响应，与团队成员相反）；团队+bot 共享前缀的混合 `configure` 中，共享设置的默认一律取排序最前的**团队** profile（bot 排序在前、且其 .env 已有 true 也不会带给全队），每个 standalone bot 单独再问一次该键（默认 true），互不串默认
- 🧹 团队命令不再误伤：`verify` 对 standalone 跳过 open_id 名单检查（"standalone bot — no roster expected"），对使用 roster-free `bot` 模板的**团队成员**同样跳过（"roster-free bot template — no roster expected"——其 SOUL 无【飞书@方式】，collect-ids 永远无法回填，不豁免则该团队 verify 永久失败）；`collect-ids`、`add/remove-member` 的名单重建与 open_id 收获、`init` 重跑的磁盘成员并集扫描均自动忽略 standalone（即使它与某团队共享前缀）；`init` 重跑时**被选中角色/coordinator 的 profile 若是 standalone bot 或元数据不可读则 fail-closed 跳过**（不覆盖其 SOUL/元数据、不进渲染名单，隐藏的 removed 标记也不会被复活）；`destroy` 永不删除共享前缀的 standalone bot（`--force` 也不删，仅提示手动清理）
- 🛡️ `.hermes-team.json` 存在但损坏（非 JSON/非对象/不可读）时不再被当作"无元数据"：`destroy`/`init` 并集扫描/`add/remove-member` 名单重建一律 fail-closed（跳过并警告，损坏文件可能藏着 standalone/removed 标记）；`collect-ids` 同样跳过（损坏 profile 不得按 legacy 后缀并入 name→open_id 全局映射、以其 per-app 隔离的 id 覆盖队友真实 id）；`configure` 按 bot 对待（警告 + `REQUIRE_MENTION` 默认 true + 不作共享设置参考）；`verify` 新增逐 profile 元数据检查（损坏即失败并指明原因，不再只剩被误读的下游症状）；`read_team_metadata` 容错语义不变、新增 `team_metadata_corrupt()` 供判定
- 🛡️ `new-bot` 事务性：SOUL 先渲染后建 profile（模板报错不再留下半建 profile 挡住重试），`--dry-run` 也先渲染一遍（无副作用）以暴露模板错误、不再给出假阳性预览；创建成功后清理 `profiles/.deleted/<name>` 墓碑（与 init/add-member 一致）；`--dry-run` 不再交互询问缺失的 `--description`（用占位符展示，CI/非 TTY 不再 Abort）；省略 `--template` 时默认模板直接取打包的 `bot.md.j2`（不再被 cwd 下同名 `bot` 文件遮蔽，显式路径仍按 cwd 解析）；`--display-name`/`--description` 非法时按字段名报错（不再误报 "Invalid template"）
- 🔒 **跨前缀隔离**：`list_team_profiles` 的前缀匹配先收紧为 `名字 == prefix 或以 prefix- 开头`（修复 `team`/`teamq` 这类字符串前缀互相吞并对方团队 profile），再对**带元数据的 profile 按其记录的 `prefix` 精确匹配**（`team`/`team-extra` 这类 dash 嵌套前缀仅靠名字无法区分）；无元数据/未记录 prefix 的 profile 回退名字匹配但**fail-closed**——前缀边界之外还带 `-` 的名字（legacy `team-extra-pm` 查询 `team`）无法归属即排除并在 destroy/collect-ids/add/remove-member/init 中说明原因（最长前缀一侧仍可操作；重跑 init 记录 prefix 即消除歧义）；`init` 对名字撞上他队成员（元数据记录了别的 prefix，**或**无记录且名字越过前缀边界的歧义名）的既有 profile fail-closed 跳过、绝不改写其 SOUL/元数据（此前会静默把对方成员/歧义 legacy profile 篡改为本队）；`add-member` 复用既有 profile 前先校验其记录的 prefix（他队 removed 成员不再被『Re-using kept profile』接手）；init 子集重跑在团队身份（团队名/总管名/hub↔coordinator）变更时对未选中成员一并**重渲染 SOUL**（模板可恢复时，收获的 open_id 照常回灌；模板失效则警告并指明真实修法——旧总管占位符 collect-ids 永远无法回填，此前是 verify 永久失败的死胡同）；所有 `--prefix` 入口拒绝空/纯空白值（空前缀会命中所有团队，`remove-member --prefix ''` 曾计划删除他队 profile）
- 🔐 凭证文件权限：`write_env` 新建 `.env` 一律 0600（不受 umask 影响），重写已存在的组/其他可读 `.env` 时收紧到 0600 并在 `configure` 输出中提示（App Secret 不再对同机其他用户可读）
- 🗑️ `destroy`：删除目录失败（OSError）时干净中止并说明（与 `remove-member` 一致，不再裸 traceback）；删除成功后写 `profiles/.deleted/<name>` 墓碑（与 `remove-member`/Hermes 删除语义统一，重 init 自动清理）
- 🔁 `init` 重跑不再破坏线上 @ 提及：重渲染前先收获现有 SOUL 的真实 open_id、渲染后回灌（与 add/remove-member 同一保证）；被并入新名单的磁盘成员其元数据 team/prefix/hub 同步刷新（否则下次 add/remove-member 按陈旧元数据把 SOUL 翻回旧团队名/旧总管）
- ✅ `verify` 的 open_id 检查按名单逐个 <at> 标签校验：任一非豁免占位符即失败并报出成员名（此前只要存在任一真实 id 就放行，add-member 后新成员无法被 @ 也 ALL PASS）；仅豁免**按名称**识别的永久占位——主人行（名「主人」，保留名）与 render-only 总管（按本 profile 元数据 hub 的名称；无 hub 记录的 legacy 团队豁免内置 M总；`"hub": null` 不豁免），不按占位 ID 豁免（key 恰为 coordinator/owner 的真实成员占位符同样是 `ou_xxx_<key>`，按 ID 豁免会永远放过不可 @ 的成员）；占位符识别的字符类放宽到 `[^"]*`（dash key 如 `ou_xxx_front-end` 此前不可见）；失败明细只列前 3 个名字、其余计入 `(+N more)`；可读但为空的 `~/.hermes/.env` 不再判为失败（无 App ID 即无从遮蔽查重；`start` 的同款告警同步改为仅真不可读时提示修权限）
- 🩹 `add/remove-member`：成员元数据**记录过**的模板失效（外部文件被删/内置名移除）时只补丁【飞书@方式】、绝不回退内置模板重渲染覆盖手写人设（仅"从未记录模板"的旧团队才回退内置）；元数据 `"hub": null`（coordinator/无总管团队的明确声明）不再被注入 legacy M总（仅完全没有 hub 记录的纯 legacy 团队保留 M总 回退）
- 🧹 其他：`collect-ids` 豁免 roster-free `bot` 模板成员（与 `verify` 口径一致，不再计入失败并给出无从执行的手填建议）；`new-bot` 拒绝保留名 `default`（Hermes 默认 profile 不在 profiles/ 下，建了也隐形）；所有打印的下一步命令对含空格 prefix 做 shell 引用（shlex.quote）；删除全仓零引用的死模板 `env.j2`/`config.yaml.j2`；`gateway_state.json` 读取显式 utf-8（C locale 下非 ASCII 记录不再被吞成"网关未运行"）；README doctor 章节与 CHANGELOG 0.3.0 的 `--fix` 描述改为实情、中文 README 移除从未发布的 Skill 宣传、README_EN 补齐 0.8.0 表述、示例改用 `init --config`
- 🧹 名单不变量补齐：`_load_roster`（add/remove-member）与 init 的磁盘并集同一规则——**多个 coordinator=true 一律 fail-closed 报错**（任选其一会让 init 与 add/remove-member 各自领不同的总管、把全队 SOUL 在两者间翻转）、key/名称重复直接报错（此前 add-member 会渲出多条相同 @ 行/多份总管）；config 声明总管时磁盘残留 coordinator profile 同样报错并点名（先清理再重跑）；磁盘 coordinator 名称纳入保留名；`.env` 属主无写位（如 0400）时写入前补齐 u+w（此前 configure 答完全部提问后在写盘处裸 PermissionError），写盘 OSError 一律转干净报错并指明 profile
- 📚 README/README_EN/CHANGELOG 同步；测试 198 → 275

## [0.7.0] - 2026-10-20

### 🪄 配置向导（new-config）

不想手写 team JSON？`hermes-team new-config [路径]` 交互式生成：

- 流程：团队名称 → 前缀 → 总管三选一（独立 profile / 主 profile 担任 render-only / 无，各带说明）→ 角色名单（可从内置 5 角色起步逐个取舍，再添加自定义角色）→ 预览 JSON → 写出
- **逐项校验**：key 字符集与重复、名称唯一性与 at 安全（`<`/`>`/换行/`\r`/保留名「主人」）非法时**立即重问该项**（名称比较按 strip 后语义，与加载器一致）；其余错误（如模板不可解析）重填该角色；前缀做路径安全校验；内置角色与已选总管/角色的 key、名称冲突时自动跳过
- 外部模板路径以绝对路径记录，保证换目录加载不失效；模板仅在与该 key 的内置默认一致时省略——显式选择（含内置 key 上选非默认模板、总管模板）始终原样写出，不静默回落
- **写盘前**先在目标目录的临时文件上用与 `init --config` 相同的加载器做**回环验证**，通过后 `os.replace` 原子替换目标文件——保证文件首次即可加载，校验失败/中断不会留下非法文件或临时残留，也不会破坏已有配置；目标文件已存在时确认覆盖并**保留原文件权限**，符号链接输出路径会更新其真实目标；输出路径是目录时直接报错（命令行参数传入的目录在问答前即报错）；打印的下一步命令对含空格的 prefix/路径做 shell 引用
- `team_config` 新增公共逐项校验器 `validate_role_key()` / `validate_role_name()`；README/README_EN/CHANGELOG 同步；测试 176 → 198

## [0.6.0] - 2026-10-20

### ➕➖ 团队成员增减（add-member / remove-member）

在已有团队上增减成员，并保持**所有成员的 SOUL 名单同步**：

- ➕ `hermes-team add-member --prefix X --key K --name N --role R [--nickname] [--template] [--clone-from]`
  - 从各 profile 的 `.hermes-team.json` 元数据重建团队名单（旧版无元数据团队回退内置角色表 + M总 render-only 占位）
  - **open_id 先收获后回灌**：改名单前先从所有 SOUL 收集已回填的真实 open_id，重渲染后再应用——增减成员永远不会把已收集的 open_id 重置成占位符；新成员的 SOUL 直接带队友的真实 open_id
  - 存量成员 SOUL 按元数据记录的模板重渲染；两种情况只补丁【飞书@方式】小节、不整体重渲染：① 旧版无元数据（legacy）成员——原团队名只存在于其 SOUL 文本，重渲染会把团队名错改成 prefix（新成员的团队名从现有 SOUL 提取复用，提取不到才回退 prefix）；② 自定义模板文件已丢失——不覆盖手写人设
- ➖ `hermes-team remove-member --prefix X --key K [--keep-profile] [--force]`
  - 默认删除 profile 目录并写 tombstone（`profiles/.deleted/<name>`，与 Hermes 删除语义一致，host 不再服务）；`--keep-profile` 只移出名单（标记持久化在该 profile 元数据里，名单重建与 collect-ids 均跳过；同 key 重新 add-member 即重新入队并清除标记）；被移除的成员在 init 重跑时保持移除——跳过并提示（含 coordinator，不再显示"将创建"）
- 🔁 init 子集重跑（`--roles`）：渲染名单为选中角色与磁盘活跃成员的**并集**（`add-member` 加入的成员、旧版无元数据 legacy profile——按 profile 后缀识别），未选中成员不再从 SOUL 名单消失（输出 `Including N on-disk member(s) ...`）；on-disk 成员与配置角色**重名时报错**（collect-ids 按名匹配）；磁盘上残留的 coordinator profile（元数据 `coordinator=true`）按总管对待、优先于配置 hub（与 add-member 的名单重建优先级一致）
- 🏷️ init 元数据新增 `template` 字段（内置名或外部模板路径），供日后重建该成员 SOUL
- 🧰 `team_config` 新增公共 `make_role_spec()`/`builtin_template_for_key()`；`open_id` 新增 `harvest_open_ids()`；init 的渲染设施改为可复用
- 📚 README/README_EN/CHANGELOG 同步；测试 108 → 176

## [0.5.0] - 2026-10-20

### 🎭 角色配置外置（team config JSON）

角色、名称、模板不再硬编码在代码里，通过 `--config` 传入 JSON 定义：

- ➕ `hermes-team init --config my-team.json`：自定义角色 key/名称/小名/职位/SOUL 模板；`team_name`/`prefix` 可在文件中给默认值（命令行参数优先）；`--roles` 变为可选的子集筛选（缺省 = 全部角色，显式空值报错而非创建全部）
- 🧠 `coordinator` 小节（可选）：声明后 init **一并创建总管 profile** 并渲染总管 SOUL——补上了此前「总管 profile 需手动创建」的缺口；总管模板缺省用内置 `coordinator.md.j2`。不声明 coordinator 时可用 `coordinator_fallback` 声明 **render-only 总管条目**（与 `coordinator` 互斥，同时声明在加载时报错；只进 roster 供成员 @，不建 profile、不参与 open_id 自动回填；`name` 必填，`role`/`nickname` 可选）；内置默认团队自带的这一条目为 `M总`，两者都未声明的自定义团队 roster 无总管条目（init 会警告）
- 📄 模板三态解析：相对 config 的**文件路径**（完全自定义人设；仅相对 config 目录解析，不再回退 cwd）/ 内置模板短名（pm/frontend/backend/qa/designer/coordinator）/ 内置角色缺省模板
- 🏷️ init 为每个 profile 写入 `.hermes-team.json` 元数据；`collect-ids` 据此按**名称**回填 open_id（自定义角色名自动回填；**声明 coordinator 时**总管 open_id 也自动回填——补上了此前「M总 open_id 需手动填」的缺口。声明了 `coordinator_fallback` 的团队（及内置默认团队）才有 render-only 总管占位、无 profile/元数据，其 open_id 不在自动回填之列；两者都未声明的自定义团队 roster 无总管条目）；无元数据的旧团队自动回退内置角色表
- 🚪 init 在部分角色创建/渲染失败时以**非 0 退出码**结束（与 verify/doctor 一致；此前失败也退出 0，脚本 `&&` 链无法感知）
- ✅ 校验：key 字符集（进入 profile 名）、key/名称全局唯一（重名会让 collect-ids 匹配歧义）、template 可解析性；坏配置在创建任何 profile 前失败
- 🧹 `verify` 的占位符 open_id 排除改为按前缀（`ou_xxx*`），不再枚举角色 key
- 📚 README/README_EN 重写「自定义角色」章节；`examples/baogoet-team/team.json` 更新为可用的配置示例

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
- 🩺 `hermes-team doctor` 命令 — 检查环境依赖与就绪状态（无参数；此前文档宣称的 `--prefix`/`--fix` 选项从未实现，v0.4.0 起增加 Hermes 版本检查并在存在失败项时以非 0 退出码结束）
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
