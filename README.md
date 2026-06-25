# quote0-burnout

AI 用量仪表盘 — OpenAI Codex + DeepSeek，支持墨水屏推送和 Windows 桌面置顶弹窗。

[English](README_EN.md)

## 功能

- **Codex**：双窗口（5h / Wk），进度条 + 余量百分比 + 重置倒计时
- **DeepSeek**：余额显示 + 状态标
- Codex 数据直连 OpenAI OAuth API，**无需 CLI 依赖**

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

# 可选 — Codex 认证（默认读取 ~/.codex/auth.json）
# export CODEX_ACCESS_TOKEN=""
# export CODEX_ACCOUNT_ID=""
```

| 变量 | 必须 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | ✓ | DeepSeek API key |
| `CODEX_ACCESS_TOKEN` | | 覆盖 Codex token（默认读 ~/.codex/auth.json） |
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
# 首次运行会自动创建 .env，编辑填入 DEEPSEEK_API_KEY 后再运行
python local_app.py
```

操作：
- **左键拖动窗口**：按住窗口任意位置拖动
- **双击**：手动刷新数据
- **右键**：弹出菜单（刷新 / 退出）
- **右下角拖动**：调整窗口大小

### 墨水屏推送

```bash
python display.py --preview    # 本地预览
python display.py              # 推送到设备
python display.py --check      # 自检
python display.py --debug-json # 打印快照 JSON
```

## 故障排查

```bash
python display.py --debug-json  # 查看数据快照
```

- **Codex 显示 "no auth"** — 运行 `codex` 重新认证，或在 .env 中设置 `CODEX_ACCESS_TOKEN`
- **DeepSeek 显示 "no key"** — 检查 .env 中 `DEEPSEEK_API_KEY` 是否正确填写
