# quote0-burnout 本地化改造设计文档

> 将墨水屏推送应用改造为 Windows 桌面置顶弹窗，实时显示 AI 额度数据。

## 1. 现状

| 项目 | 说明 |
|------|------|
| 运行平台 | macOS / Linux（bash 脚本 + launchd 定时） |
| 数据源 | Codex（OpenAI wham API）、DeepSeek（balance API） |
| 输出方式 | Pillow 渲染 296×152 黑白 PNG → 推送到 Quote/0 墨水屏 |
| 依赖 | requests、Pillow |
| 配置 | `.env` 文件（API Key、Device ID 等） |

核心数据获取逻辑在 `display.py` 中，与推送逻辑耦合。

## 2. 目标

- Windows 桌面置顶弹窗，显示 Codex + DeepSeek 额度数据
- 每 5 分钟自动刷新
- 半透明背景，像素风格字体，视觉风格延续原项目
- 配置方式不变，继续用 `.env`

## 3. 架构设计

### 3.1 文件结构

```
quote0-burnout/
├── display.py          # 保留：数据获取 + snapshot 构建（去掉推送逻辑）
├── render.py           # 保留：墨水屏渲染（原功能不动）
├── local_app.py        # 新增：Windows 桌面置顶弹窗主程序
├── config.example.env   # 保留
├── requirements.txt    # 更新：去掉 Pillow（local_app 不需要）
├── assets/
│   └── fonts/          # 保留：像素字体
└── docs/
    └── local-app-design.md  # 本文档
```

### 3.2 模块职责

**`display.py`（改造）**

保留：
- `_load_codex_token()` — 加载 Codex 认证
- `get_codex_usage()` — 获取 Codex 用量
- `get_deepseek_balance()` — 获取 DeepSeek 余额
- `build_codex_snapshot()` — 构建 Codex 快照
- `build_deepseek_snapshot()` — 构建 DeepSeek 快照
- `build_snapshot()` — 构建完整快照
- `_time_until()` — 时间格式化
- `_pct_status()` / `_balance_status()` — 状态判断

去掉（或标记为可选）：
- `push_image()` / `push_text()` — Quote/0 推送
- `run()` 中的推送逻辑
- `check()` 中的 Quote/0 端点检查
- `list_tasks()` — Quote/0 任务管理
- Quote/0 相关配置变量（`QUOTE0_API_KEY`、`QUOTE0_DEVICE_ID` 等）

**`local_app.py`（新增）**

职责：
- 加载 `.env` 配置
- 调用 `display.py` 的 `build_snapshot()` 获取数据
- 用 tkinter 渲染置顶窗口
- 定时刷新（默认 5 分钟）

### 3.3 数据流

```
.env 配置
    │
    ▼
display.py :: build_snapshot()
    │
    ├── get_codex_usage()     → chatgpt.com API
    └── get_deepseek_balance() → deepseek.com API
    │
    ▼
snapshot dict
    │
    ▼
local_app.py :: tkinter 窗口渲染
    │
    └── 每 5 分钟循环刷新
```

## 4. 窗口设计

### 4.1 布局

```
┌─────────────────────────────────┐
│  16:40              ○ C  ○ D   │  ← 标题栏：时间 + 状态灯
├─────────────────────────────────┤
│  ◆ CODEX                        │
│  5h  [████████████░░░░] 89% 2h  │  ← 短窗口：进度条 + 百分比 + 重置倒计时
│  Wk  [████████░░░░░░░] 69% 5d  │  ← 长窗口：同上
│─────────────────────────────────│
│  ◆ DEEPSEEK                     │
│  $18.42                    OK   │  ← 余额大字 + 状态
└─────────────────────────────────┘
```

### 4.2 样式参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 窗口尺寸 | 约 320 × 220 px | 紧凑，不遮挡工作区 |
| 置顶 | `topmost=True` | 始终在最前 |
| 可拖动 | 绑定鼠标事件 | 按住标题栏拖动 |
| 背景色 | `#1e1e2e`（深色） | 半透明效果 |
| 文字色 | `#cdd6f4`（浅色） | Catppuccin 风格 |
| 进度条 | 剩余量填充，颜色随状态变化 | ok=绿 warn=黄 hot=红 |
| 字体 | PixelOperator 14px / VCR OSD Mono 20px | 复用 assets/fonts |
| 刷新间隔 | 5 分钟（可配置） | `REFRESH_INTERVAL` 环境变量 |
| 边框 | 无边框（`overrideredirect`） | 干净外观 |

### 4.3 交互

- **左键拖动标题栏**：移动窗口位置
- **右键托盘图标**：退出程序
- **双击窗口**：手动立即刷新
- **系统托盘**：最小化到托盘，不占任务栏

## 5. 配置变更

`.env` 文件简化：

```env
# 必填
DEEPSEEK_API_KEY="sk-xxx"

# 可选（默认读 ~/.codex/auth.json）
# CODEX_ACCESS_TOKEN=""
# CODEX_ACCOUNT_ID=""

# 本地弹窗配置
REFRESH_INTERVAL=300    # 刷新间隔（秒），默认 300
WINDOW_OPACITY=0.92      # 窗口不透明度 0.0-1.0，默认 0.92
```

去掉 Quote/0 相关配置（`QUOTE0_API_KEY`、`QUOTE0_DEVICE_ID`、`QUOTE0_IMAGE_TASK_KEY` 等）。

## 6. 技术选型

| 选项 | 选定 | 理由 |
|------|------|------|
| GUI 框架 | tkinter | Python 内置，零额外依赖 |
| 系统托盘 | pystray | 轻量，跨平台 |
| 定时器 | tkinter `after()` | 内置，无需线程 |
| 字体渲染 | Pillow + tkinter ImageTk | 支持自定义 TTF 字体 |
| 打包分发 | PyInstaller（可选） | 后期可打包为 exe |

新增依赖：`pystray`（仅系统托盘功能需要）。

## 7. 实施步骤

1. **改造 `display.py`**：将数据获取逻辑抽取为独立模块，去掉 Quote/0 推送代码，保留 `build_snapshot()` 作为对外接口
2. **新建 `local_app.py`**：
   - 加载 `.env`
   - 创建 tkinter 置顶窗口
   - 实现数据渲染（文字 + 进度条）
   - 实现定时刷新
   - 实现系统托盘
   - 实现窗口拖动
3. **更新 `requirements.txt`**
4. **测试验证**

## 8. 兼容性

- 原有墨水屏功能（`display.py --preview`、`--push`）不受影响，`local_app.py` 是独立入口
- `render.py` 和 `widget/` 目录保持不变
- macOS 用户仍可使用原 `run.sh` 流程

## 9. 风险与约束

- Codex token 有效期有限，过期后需重新通过 `codex` CLI 认证
- DeepSeek API 可能有频率限制，5 分钟间隔足够安全
- tkinter 在 Windows 高 DPI 下可能需要额外处理（`ctypes` 设置 DPI 感知）
- `overrideredirect` 模式下窗口无标题栏，需自行处理拖动和关闭
