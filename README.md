# LLM 用量监控 SwiftBar 插件（多平台版）

中文 | [English](README.en.md)

macOS 菜单栏插件，用于展示多平台 LLM 的用量与重置窗口。基于 [SwiftBar](https://github.com/swiftbar/SwiftBar)。

当前版本已完成**统一架构**，并支持通过 SwiftBar 图形交互添加平台账号（无需手改配置文件）。优先提供对 `new_api` 类型供应商的自动拉取能力；`Cursor` 与 `Trae.ai` 当前以手工窗口模式接入（后续可升级为官方 API 适配）。

## 已实现能力

- **统一架构（Provider 可插拔）**
  - 平台适配层与渲染层解耦
  - 新平台接入可独立扩展，不影响核心菜单渲染
- **统一展示层级**
  - 按「平台 > 账号 > 窗口」展示
  - 支持指定主账号（菜单栏顶部百分比取自主账号）
- **窗口分类标准化**
  - 日、5 小时、周、月、自定义、不重置（共 6 类）
- **SwiftBar 图形化配置**
  - 菜单中直接添加账号、设置主账号、添加/清空窗口、删除账号
  - 适合后续贡献者快速试配新平台
- **多账号支持**
  - 同平台可配置多个账号
- **Keychain 凭证支持**
  - new_api 的 API Key 可写入 macOS Keychain（默认服务名 `llm-usage-swiftbar`）
- **缓存机制**
  - 30 分钟缓存，避免频繁请求上游接口

## 当前平台状态

### 1) New API（优先）

- 支持以 `Base URL + API Key` 接入
- 可选手动指定 usage path；未指定时会自动尝试常见路径（如 `/api/usage/token`、`/api/usage` 等）
- 自动解析常见字段组合（如 `used/total/remaining` 或 `utilization`）
- 若远程接口不可用，会自动回退到手工窗口

### 2) Cursor（低优先级：手工模式）

- 当前不默认依赖非官方接口
- 通过手工窗口维护用量与重置时间

### 3) Trae.ai（低优先级：手工模式）

- 当前不默认依赖非官方接口
- 通过手工窗口维护用量与重置时间

## 前置条件

- **macOS**（SwiftBar 仅支持 macOS）
- **Python 3.9+**
- **SwiftBar**

## 安装

```bash
git clone https://github.com/andreashen/usage-swiftbar.git
cd usage-swiftbar
./install.sh
```

安装脚本会自动：

1. 检查 macOS 环境
2. 通过 Homebrew 安装 SwiftBar（若未安装）
3. 检查 `python3`
4. 安装插件到 `~/Library/SwiftBar/claude-usage.5m.py`
5. 启动 SwiftBar（若未运行）

## 配置（全部走 SwiftBar 图形界面）

首次安装后，菜单栏会显示 `◆ 配置`。点击后按菜单操作：

1. `➕ 添加平台账号`
2. 选择平台（new_api / cursor / trae）
3. 填写账号名称
4. （new_api）填写 Base URL、可选 usage path、可选 API Key
5. 可立即添加手工窗口

你还可以在账号菜单中执行：

- `设为主账号`
- `添加手工窗口`
- `清空手工窗口`
- `删除账号`

## 用量窗口类型（统一六类）

- 日（day）
- 5小时（five_hour）
- 周（week）
- 月（month）
- 自定义（custom）
- 不重置（no_reset）

其中：
- 非“不重置”窗口可填写 `resets_at`（ISO8601）
- 自定义窗口可额外填写总时长（小时），用于“时间进度”计算

## 刷新与缓存

- 插件刷新周期由脚本文件名 `claude-usage.5m.py` 控制（5 分钟）
- 内置 30 分钟缓存，避免上游限流
- 菜单中可使用 `♻️ 清空缓存并刷新`

## 配置文件与缓存文件

- 配置文件：`~/.config/llm-usage-swiftbar/config.json`
- 缓存文件：`~/.local/state/llm-usage-cache.json`

## 卸载

```bash
rm -f ~/Library/SwiftBar/claude-usage.5m.py
rm -f ~/.config/llm-usage-swiftbar/config.json
rm -f ~/.local/state/llm-usage-cache.json
```

## 致谢

- 感谢上游项目 [joewongjc/claude-usage-swiftbar](https://github.com/joewongjc/claude-usage-swiftbar) 提供启发。
- 感谢 [SwiftBar](https://github.com/swiftbar/SwiftBar) 的插件生态。

## 开源协议

MIT
