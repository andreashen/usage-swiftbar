# LLM 用量监控 SwiftBar 插件（多平台）

中文 | [English](README.en.md)

macOS 菜单栏插件，用于展示各类 LLM 平台的远程 API / 官方客户端用量与重置窗口。基于 [SwiftBar](https://github.com/swiftbar/SwiftBar)。

本仓库由早期单平台用量插件 fork 演进而来，当前以“**多平台可扩展架构**”为目标推进（需求边界见 `docs/spec.md`）。README 仅包含安装与使用说明。

## 功能

### 已支持（当前实现）

- **统一展示层级** - 平台 > 账号 > 窗口（含主账号规则）
- **多账号管理** - 同平台可多个账号，可在菜单中设置主账号、删除账号
- **用量窗口模型** - 日 / 5 小时 / 周 / 月 / 自定义 / 不重置（手工窗口为兜底）
- **New API（官方接口）** - 可配置 Base URL + User ID + 用户级系统访问令牌，支持“测试连接（三级红绿灯）”后保存
- **手工窗口模式** - `Cursor`、`Trae.ai` 等可先以手工窗口录入用量百分比
- **智能缓存** - 30 分钟缓存避免频繁请求，支持清缓存/立即刷新

### 规划中（以 `docs/spec.md` 为准）

- **统一展示模型/账号维度** - 以“平台 + 账号 + 模型/套餐”为维度聚合
- **可插拔平台适配** - 新增平台不影响已有平台展示与缓存逻辑
- **更多平台** - 逐步引入新的 LLM 提供方与代理平台（以实际实现为准）

## 前置条件

- **macOS**（SwiftBar 仅支持 macOS；配置弹窗依赖 `osascript`）
- **Python 3.9+**
- **Homebrew**（安装 SwiftBar）

安全与存储：

- **敏感信息**（例如 `new_api` 访问令牌）可存储于 **macOS Keychain**
- **非敏感信息**（例如 Base URL）存于本地配置文件

## 安装

### 手动安装

```bash
git clone https://github.com/andreashen/usage-swiftbar.git
cd usage-swiftbar
./install.sh
```

安装脚本会自动:

1. 通过 Homebrew 安装 [SwiftBar](https://github.com/swiftbar/SwiftBar)（如果没装）
2. 复制插件到 `~/Library/SwiftBar/`
3. 启动 SwiftBar（如果没运行）

## 效果展示

菜单栏显示：`◆ 55%`（主账号的主窗口百分比，颜色随用量变化）

点击展开详情:

```
New API / Cursor / Trae.ai（示例）
─────────────────────────────
📅 Weekly (7d)  剩余 4d 2h
  用量  ███████████           55%
  时间  ██████████████████    90%
─────────────────────────────
📅 Sonnet (7d)
  用量                         2%
  时间  ██████████████████    89%
─────────────────────────────
⏱ 5-Hour Burst  剩余 1h 11m
  用量  ████████              39%
  时间  ███████████████       76%
─────────────────────────────
已更新 18:48
立即刷新
```

### 颜色含义

| 用量    | 颜色    | 含义     |
| ------- | ------- | -------- |
| 0-19%   | 🟢 绿色 | 配额充裕 |
| 20-39%  | 🔵 蓝色 | 正常使用 |
| 40-59%  | 🟡 黄色 | 已过半   |
| 60-79%  | 🟠 橙色 | 有点吃紧 |
| 80-100% | 🔴 红色 | 快用完了 |

## 配置

插件每 5 分钟刷新一次（由文件名 `llm-usage.5m.py` 中的 `5m` 决定）。改文件名即可调整刷新频率:

- `llm-usage.1m.py` - 每分钟
- `llm-usage.10m.py` - 每 10 分钟
- `llm-usage.30m.py` - 每 30 分钟

无论刷新频率如何，API 调用都有 30 分钟缓存以避免限流。缓存过期后点"立即刷新"可强制拉取最新数据。

> **提示:** 当前脚本文件名为 `llm-usage.*.py`，刷新频率机制不变。

### 通过菜单完成配置（不需要手工编辑配置文件）

- **添加账号**：菜单选择“添加账号”，按提示选择平台并完成配置
  - `new_api`：同一弹窗输入账号名称 / Base URL / 用户 ID / 用户级系统访问令牌；先“测试连接”（三级全绿）再允许保存
  - `Cursor` / `Trae.ai`：当前以“手工窗口模式”接入，可先录入用量百分比作为兜底
- **管理账号**：可设置主账号、删除账号
- **手工窗口**：可为任意账号新增/清空窗口（按日/5小时/周/月/自定义/不重置）
- **缓存**：可清空缓存后刷新

## 卸载

```bash
rm ~/Library/SwiftBar/llm-usage.5m.py
rm -f ~/.local/state/llm-usage-cache.json
rm -f ~/.config/llm-usage-swiftbar/config.json
```

如曾配置过 `new_api` 令牌，相关密钥存于 macOS Keychain；建议先在菜单中删除账号以清理 Keychain 条目。

## 致谢

- 感谢上游项目 [joewongjc/claude-usage-swiftbar](https://github.com/joewongjc/claude-usage-swiftbar) 提供的灵感与早期实现。
- 感谢 [SwiftBar](https://github.com/swiftbar/SwiftBar) 让菜单栏插件生态变得简单易用。

> **说明：**本仓库为独立演进的 fork 版本。

## 开源协议

MIT
