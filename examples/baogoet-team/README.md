# BaGoet 团队搭建实例

## 背景

BaGoet 是一个由 6 个 AI Agent 组成的飞书协作团队，用于验证 hermes-multi-agent-team 工具的实战效果。

## 团队成员

| 角色 | 名称 | 小名 | 职责 |
|------|------|------|------|
| 总管 | M总 | 小m | 任务协调、进度跟踪、汇报汇总 |
| 产品 | P酱 | 小P | 需求分析、PRD撰写、用户故事 |
| 前端 | F仔 | 小F | Vue/React开发、界面实现 |
| 后端 | B叔 | 小B | API设计、数据库、服务端逻辑 |
| 测试 | Q宝 | 小Q | 测试用例、Bug报告、质量验证 |
| 设计 | U酱 | 小U | UI设计、交互设计、设计规范 |

## 搭建过程

在本目录（`examples/baogoet-team/`）下执行，`init` 直接读取 `team.json`（6 角色：coordinator `M总` + pm/fe/be/qa/ui，prefix `baoget` 已在文件中声明）：

```bash
# 1. 初始化团队（按 team.json 的角色与总管声明创建 profile）
hermes-team init --config team.json

# 2. 配置飞书凭证（每个角色一个独立飞书App）
hermes-team configure --prefix baoget

# 3. 启动所有gateway
hermes-team start --prefix baoget

# 4. 在飞书群里@所有人，触发消息
# 5. 自动收集open_id
hermes-team collect-ids --prefix baoget

# 6. 验证配置
hermes-team verify --prefix baoget
```

## 踩过的坑

1. **open_id per-app隔离** — 同一个人在不同bot视角下open_id不同
2. **cli_xxx不能用于@mention** — 必须用ou_xxx格式
3. **事件订阅必须选"接收群中所有消息"** — 否则bot收不到其他bot的消息
4. **ALLOW_BOTS必须设为all** — 否则bot忽略其他bot的消息
5. **REQUIRE_MENTION必须设为false** — 否则bot只响应被@的消息

详见 `README.md` 的 Pitfalls 章节。
