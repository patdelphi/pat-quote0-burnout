# quote0-burnout

AI 用量仪表盘 — OpenAI Codex + DeepSeek，支持墨水屏推送和 Windows 桌面置顶弹窗。

[English](README_EN.md)

## 功能

- **Codex**：双窗口（5h / Wk），进度条 + 余量百分比 + 重置倒计时
- **DeepSeek**：余额显示 + 状态标
- Codex 数据默认通过 Codex CLI 的 `app-server` 获取，自动复用当前登录状态
- 旧版环境自动回退到 OpenAI OAuth HTTP 接口；JSBox 小组件使用兼容 HTTP 接口

## 两种模式

### Windows 桌面弹窗（本地化）

```
┌──────────────────────────────────┐
│  16:40              ● C  ● D     │
│──────────────────────────────────│
│  ◆ CODEX                          │
│  5h ████████████████░░░  27% / 21:30 │
│  Wk ██████░░░░░░░░░░░░  82% / 06/30 │
│──────────────────────────────────│
│  ◆ DEEPSEEK              $18.42   │
└──────────────────────────────────┘
```

- tkinter 无边框置顶窗口，深色主题
- 首次运行自动创建 `.env` 配置文件
- 每 5 分钟自动刷新，**双击**手动刷新
- **左键拖动**移动窗口，**右下角拖动**调整大小
- **右键菜单**：刷新 / 退出
- 半透明背景

### 墨水屏推送（原版）

```
                        16:40
◆ CODEX
5h  [████████████░░░░░] 89%  4h41m
Wk  [████████░░░░░░░░] 69%  5d23h
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
◆ DEEPSEEK
$18.42                        OK
```

## 安装

```bash
pip install -r requirements.txt
```

## 配置

首次运行 `python local_app.py` 会自动创建 `.env` 文件。编辑 `.env` 填入密钥：

```bash
# 必填
export DEEPSEEK_API_KEY="sk-xxx"

# 可选 — 自定义 Codex CLI 路径（默认从 PATH 查找 codex）
# export CODEX_COMMAND=""

# 兼容回退 — 默认读取 ~/.codex/auth.json，也可用环境变量覆盖
# export CODEX_ACCESS_TOKEN=""
# export CODEX_ACCOUNT_ID=""
```

| 变量 | 必须 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | ✓ | DeepSeek API key |
| `CODEX_COMMAND` | | Codex CLI 路径；默认从 PATH 查找 `codex` |
| `CODEX_ACCESS_TOKEN` | | 无法使用 app-server 时覆盖 OAuth token |
| `CODEX_ACCOUNT_ID` | | Codex 账户 ID |
| `REFRESH_INTERVAL` | | 刷新间隔（秒），默认 300 |
| `WINDOW_OPACITY` | | 窗口不透明度 0.0-1.0，默认 0.92 |
| `FONT_FAMILY` | | 字体名称，默认 Arial |
| `FONT_SIZE` | | 基础字号（px），默认 10 |
| `FONT_SIZE_LARGE_OFFSET` | | 余额字号增量，默认 0（即全部统一大小） |
| `QUOTE0_API_KEY` | | Quote/0 API key（墨水屏模式） |
| `QUOTE0_DEVICE_ID` | | 设备 ID（墨水屏模式） |

> 字体支持跨平台自动兜底：若配置的字体不存在，Windows 回退到 Microsoft YaHei / Arial，macOS 回退到 PingFang SC / Helvetica，Linux 回退到 WenQuanYi Micro Hei / DejaVu Sans。

## 使用

### Windows 桌面弹窗

```bash
# 首次运行会自动创建 .env 与 .env.sample，编辑 .env 填入 DEEPSEEK_API_KEY 后再运行
python local_app.py
```

操作：
- **左键拖动窗口**：按住窗口任意位置拖动
- **双击**：手动刷新数据
- **F5**：刷新数据；**+ / -**：放大 / 缩小字体（窗口获得焦点时生效）
- **/**：降低不透明度；**\***：提高不透明度（窗口获得焦点时生效）
- **右键**：弹出菜单（刷新 / 最小化到托盘 / 退出）
- **右下角拖动**：调整窗口大小
- **最小化到托盘**：右键 → "最小化到托盘"，隐藏到系统托盘（任务栏不显示）；双击托盘图标恢复窗口，托盘菜单可"退出"

### 墨水屏推送

```bash
python display.py --preview    # 本地预览
python display.py              # 推送到设备
python display.py --check      # 自检
python display.py --debug-json # 打印快照 JSON
```

### Rand/0 Display Mode（本地 WebSocket）

将 200×200 仪表盘通过本地 WebSocket 推送到 MindReset Rand/0 设备的 Display Mode，支持黑白与四级灰：

```bash
python display.py --display-mode 192.168.1.100          # 黑白（默认）
python display.py --display-mode 192.168.1.100 --gray4  # 四级灰
python rand0_display.py --preview --mode gray4          # 本地预览 200×200
```

需要设备已进入 Display Mode 并显示 IP，且与电脑在同一局域网。依赖 `websocket-client`。

本地窗口（手动预览/推送 + 可选定时自动推送）：

```bash
# 首次运行会自动创建 .env 与 .env.sample
python rand0_app.py
```

点窗口**最小化**按钮即隐藏到系统托盘（任务栏不显示）；双击托盘图标恢复，托盘菜单可"退出"。勾选"反显"可切换黑底白字显示并立即刷新预览、写回 .env 持久化。设备端文字优先使用系统**微软雅黑粗体**（找不到时回退内置像素字体）。启用自动定时推送后，启动即立即拉取数据推送一帧，之后按设定间隔推送；反显切换、推送配置均自动写回 .env。

### 打包为 exe

两个入口各自可打包成独立单文件 exe，字体等资源已内置，无需额外拷贝 assets。

**Windows 桌面弹窗（local_app.py）**

```bash
pyinstaller --noconfirm --onefile --windowed --name Quote0Local --add-data "assets;assets" local_app.py
```

产物在 `dist\Quote0Local.exe`。首次运行会在 exe **同目录自动创建 `.env`**，编辑填入 `DEEPSEEK_API_KEY` 后再运行。

**墨水屏推送窗口（rand0_app.py）**

```bash
pyinstaller --noconfirm --onefile --windowed --name Rand0Display --add-data "assets;assets" rand0_app.py
```

产物在 `dist\Rand0Display.exe`。运行 exe 优先读取**同目录下的 `.env`**（若不存在则跳过）。首次运行若 DeepSeek 显示 "no key"，请在 exe 同目录自建 `.env` 并填写：

```bash
export DEEPSEEK_API_KEY="你的key"
```

## 故障排查

```bash
python display.py --debug-json  # 查看数据快照
```

- **Codex 显示 "no auth"** — 运行 `codex login` 重新认证；旧版环境可设置 `CODEX_ACCESS_TOKEN`
- **DeepSeek 显示 "no key"** — 检查 .env 中 `DEEPSEEK_API_KEY` 是否正确填写
