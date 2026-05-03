# LLM 用量监控 SwiftBar 插件（多平台支持演进中）

中文 | [English](README.en.md)

macOS 菜单栏插件，用于展示各类 LLM 平台的远程 API / 官方客户端用量与重置窗口。基于 [SwiftBar](https://github.com/swiftbar/SwiftBar)。

当前仓库由 Claude Code 用量插件 fork 演进而来：**现阶段仍只支持 Claude Code**（OAuth / macOS Keychain）。本文档已按“通用化、多平台可扩展”的目标更新，新平台将逐步引入。

## 功能

### 已支持（当前实现：Claude Code）

- **实时用量监控** - Weekly (7 天)、Sonnet/Opus 分模型、5 小时 Burst 窗口
- **五档颜色进度条** - 绿/蓝/黄/橙/红，抬头瞄一眼就知道配额够不够
- **时间进度对比** - 用量进度 vs 时间进度，一眼判断“省着用/放心用”
- **超额用量追踪** - 开启了 Extra Usage 的话，显示消费金额和额度
- **智能缓存** - 30 分钟缓存避免 API 限流，支持手动刷新
- **自动识别套餐** - 自动显示 Pro / Max / Max 5x / Max 20x

### 规划中（多平台）

- **统一展示模型/账号维度** - 以“平台 + 账号 + 模型/套餐”为维度聚合
- **可插拔平台适配** - 新增平台不影响已有平台展示与缓存逻辑
- **更多平台** - 逐步引入新的 LLM 提供方与代理平台（以实际实现为准）

## 前置条件

### 当前（现有实现：Claude Code）

- **macOS**（SwiftBar 仅支持 macOS）
- **Claude Code**，且已通过 `claude login` 登录（OAuth 认证）
- **Python 3.9+**（macOS 自带）

> **注意:** 当前版本通过 macOS Keychain 读取 Claude Code OAuth 凭证，不支持 API Key 方式（`ANTHROPIC_API_KEY`）。必须先用 `claude login` 登录。

### 未来（多平台）

不同平台会有不同认证方式（API Key / OAuth / 企业网关等）。仓库会在引入对应平台时补齐具体前置条件与配置方式。

## 安装

### 用 Claude Code 安装（推荐）

把这个 repo 链接丢给你的 Claude Code，让它帮你装就行。

### 手动安装

```bash
git clone https://github.com/andreashen/usage-swiftbar.git
cd usage-swiftbar
./install.sh
```

安装脚本会自动:

1. 通过 Homebrew 安装 [SwiftBar](https://github.com/swiftbar/SwiftBar)（如果没装）
2. 检查 Claude Code OAuth 凭证是否存在
3. 复制插件到 `~/Library/SwiftBar/`
4. 启动 SwiftBar（如果没运行）

## 效果展示

菜单栏显示: `◆ 55%`（周用量百分比，颜色随用量变化）

点击展开详情:

```
Claude Max 5x
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

插件每 5 分钟刷新一次（由文件名 `claude-usage.5m.py` 中的 `5m` 决定）。改文件名即可调整刷新频率:

- `claude-usage.1m.py` - 每分钟
- `claude-usage.10m.py` - 每 10 分钟
- `claude-usage.30m.py` - 每 30 分钟

无论刷新频率如何，API 调用都有 30 分钟缓存以避免限流。缓存过期后点"立即刷新"可强制拉取最新数据。

> **提示:** 当前脚本文件名仍为 `claude-usage.*.py`，后续在完成多平台改造时可能会调整为更通用的命名，但刷新频率机制不变。

## 卸载

```bash
rm ~/Library/SwiftBar/claude-usage.5m.py
rm -f ~/.local/state/claude-usage-cache.json
```

## 致谢

- 感谢上游项目 [joewongjc/claude-usage-swiftbar](https://github.com/joewongjc/claude-usage-swiftbar) 提供的灵感与早期实现。
- 感谢 [SwiftBar](https://github.com/swiftbar/SwiftBar) 让菜单栏插件生态变得简单易用。

> **说明：**本仓库为独立演进的 fork 版本。

## 开源协议

MIT
