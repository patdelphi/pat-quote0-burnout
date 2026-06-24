# quote0-burnout

AI 用量仪表盘 — OpenAI Codex + DeepSeek，支持墨水屏推送和 Windows 桌面置顶弹窗。

[English](README_EN.md)

## 功能

- **Codex**：双窗口（5h / Wk），进度条 + 余量百分比 + 重置倒计时
- **DeepSeek**：余额大字显示 + 状态标
- Codex 数据直连 OpenAI OAuth API，**无需 CLI 依赖**

## 两种模式

### Windows 桌面弹窗（本地化）

```
┌──────────────────────────────────┐
│  16:40              ● C  ● D     │
│──────────────────────────────────│
│  ◆ CODEX                          │
│  5h ████████████████░░░  27% / 4h │
│  Wk ██████░░░░░░░░░░░░  82% / 5d │
│──────────────────────────────────│
│  ◆ DEEPSEEK                        │
│  $18.42                            │
└──────────────────────────────────┘
```

- tkinter 无边框置顶窗口，深色主题
- 每 5 分钟自动刷新，双击手动刷新
- 支持拖动、右键菜单（刷新/退出）
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

```bash
cp config.example.env .env
# 编辑 .env 填入密钥
```

| 变量 | 必须 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | ✓ | DeepSeek API key |
| `CODEX_ACCESS_TOKEN` | | 覆盖 Codex token（默认读 ~/.codex/auth.json） |
| `CODEX_ACCOUNT_ID` | | Codex 账户 ID |
| `REFRESH_INTERVAL` | | 刷新间隔（秒），默认 300 |
| `WINDOW_OPACITY` | | 窗口不透明度 0.0-1.0，默认 0.92 |
| `QUOTE0_API_KEY` | | Quote/0 API key（墨水屏模式） |
| `QUOTE0_DEVICE_ID` | | 设备 ID（墨水屏模式） |

## 使用

### Windows 桌面弹窗

```bash
python local_app.py
```

### 墨水屏推送

```bash
python display.py --preview   # 本地预览
python display.py             # 推送到设备
python display.py --check     # 自检
python display.py --debug-json # 打印快照 JSON
```

## 故障排查

```bash
python display.py --debug-json  # 查看数据快照
```

- **Codex 显示 "no auth"** — 运行 `codex` 重新认证，或在 .env 中设置 `CODEX_ACCESS_TOKEN`
- **DeepSeek 显示 "no key"** — 检查 .env 中 `DEEPSEEK_API_KEY` 是否正确填写
