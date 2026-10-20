# 🤝 贡献指南

感谢你对 `hermes-multi-agent-team` 的兴趣！欢迎通过 PR 参与贡献。

---

## 🚀 快速开始

### 1. Fork & Clone

```bash
# Fork 仓库后 clone
git clone https://github.com/<your-username>/hermes-multi-agent-team.git
cd hermes-multi-agent-team
```

### 2. 安装开发依赖

```bash
pip install -e ".[dev]"
```

### 3. 确认环境

```bash
# 检查依赖
hermes-team doctor

# 跑测试
pytest tests/ -v

# 检查 lint
ruff check .
```

---

## 📐 开发规范

### 代码风格

- **Linter**: [Ruff](https://github.com/astral-sh/ruff)
- **行宽**: 100 字符
- **Python 版本**: ≥ 3.10
- 提交前请运行：

```bash
ruff check .          # 检查
ruff check --fix .    # 自动修复
ruff format .         # 格式化
```

### 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <description>

# 示例
feat(commands): add doctor command
fix(init): handle missing template file
docs(readme): update installation steps
test(destroy): add force-delete test case
```

**Type 类型：**
| Type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `test` | 测试相关 |
| `refactor` | 重构（不改变功能） |
| `chore` | 工程化（CI、依赖等） |

---

## 🎭 新增角色模板

如果你想为团队添加新角色（如 DevOps、数据分析师等），按以下步骤：

### Step 1: 创建模板文件

在 `hermes_multi_agent_team/templates/SOUL/` 下新建 `xxx.md.j2`：

```markdown
你是{{ name }}，小名"{{ nickname }}"，团队的 [角色名]～

【身份】
你是{{ team_name }}团队的[角色]，负责[职责描述]。

【性格】
- [性格特点]

【能力】
- [专业技能]

【工作方式】
- 收到任务后的流程
- 完成后只 @{{ coordinator_name|default('总管') }} 汇报

【团队协作规则】⭐ 重要！
- 🎯 Hub-and-Spoke 模式（星型协作）：总管是中心节点
- ✅ 完成任务后 → 只 @总管 汇报
- ✅ 需要其他人配合时 → 先 @总管 说明需求，由总管统一分派
- ❌ 不要直接 @其他成员安排任务
- ❌ 不要和其他成员直接讨论，一切通过总管协调

【飞书@方式】（发消息时用以下格式@其他成员）
{% for member in team_members %}
- @{{ member.name }}（{{ member.role }}）：`<at user_id="{{ member.open_id }}">{{ member.name }}</at>`
{% endfor %}

【说话风格】
- [语言风格描述]

【禁止】
- 不做其他角色的事
```

### Step 2: 注册角色

角色定义在 `hermes_multi_agent_team/team_config.py`，按需选择：

```python
# ① _BUILTIN_TEMPLATES：注册模板短名，自定义团队即可用 "template": "devops" 复用
_BUILTIN_TEMPLATES: dict[str, str] = {
    # ...已有的条目...
    "devops": "devops.md.j2",
}

# ② builtin_team_config() 的 roles 列表：把角色纳入默认团队
#    （内置 key 不写 template 也能解析）
roles = [
    RoleSpec(key="devops", name="D哥", nickname="小D", role="DevOps", template="devops.md.j2"),
]
```

也可以完全不改代码：写一个团队 JSON 配置，用 `hermes-team init --config my-team.json` 引用你的模板文件（路径相对 config），详见 README「自定义角色」。

### Step 3: 提交 PR

- 模板必须包含 **【团队协作规则】** 章节
- 模板必须使用 Jinja2 变量（`{{ name }}`、`{{ nickname }}` 等）
- 添加测试用例验证模板渲染

---

## 🧪 测试

### 运行测试

```bash
# 全部测试
pytest tests/ -v

# 单个文件
pytest tests/test_init.py -v

# 带覆盖率
pytest tests/ -v --cov=hermes_multi_agent_team
```

### 测试规则

⚠️ **绝对不要测试真实环境！**

- ✅ 使用 `tmp_path` fixture 创建临时目录
- ✅ 使用 `monkeypatch` mock `subprocess.run`
- ✅ 使用 CliRunner 测试 CLI 命令
- ❌ 不要读写 `~/.hermes/profiles/` 下的真实文件
- ❌ 不要执行真实的 `hermes` 命令

示例：

```python
def test_my_feature(tmp_hermes_home, mock_subprocess_success):
    """测试用例必须使用 fixtures 隔离环境。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--team-name", "Test", "--roles", "pm", "--prefix", "t"])
    assert result.exit_code == 0
```

---

## 📝 PR 流程

1. **Fork** 仓库
2. 创建分支：`git checkout -b feat/my-feature`
3. 写代码 + 测试
4. 确保 `ruff check .` 和 `pytest` 都通过
5. 提交 PR，填写描述：
   - 改了什么
   - 为什么改
   - 关联的 Issue（如有）
6. 等待 review

---

## 🐛 报告 Issue

遇到问题？请在 GitHub Issues 中反馈，包含：

- 操作系统和 Python 版本
- Hermes Agent 版本
- 完整的错误日志
- 复现步骤

---

## 📄 License

提交的代码将遵循项目的 [MIT License](LICENSE)。
