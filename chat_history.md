# Chat History

## 2026-09-20 14:00:00 +08:00

- 用户：打包 local_app.py 为 exe，更新 README。
- 助手：为 local_app.py 封装 `_config_dir()`（exe 同目录读写 .env）/`_resource_dir()`（_MEIPASS 读字体），打包生成 `dist\Quote0Local.exe` 并验证自动建 .env；README 打包段拆分为弹窗与墨水屏两个子节说明各自打包命令。

- 用户：为 Rand/0 Display Mode 窗口用 PyInstaller 打包为 exe。
- 助手：修正打包下 `.env` 读取路径为 exe 同目录、字体走 `_MEIPASS`；打包生成 `dist\Rand0Display.exe`（36.2MB）；整理 reset 行字号由 12px 加大到 16px；`rand0_app.py` 顶部加载 `.env` 并入参（IP/模式/间隔/超时）脚本回写 .env；注意 dist 不复制真实 .env，key 由使用者自填。

## 2026-08-27 18:35:39 +08:00

- 用户：修改代码，适配 Codex 新的额度获取方式。
- 助手：将 Python 默认额度来源改为 Codex CLI app-server 的 `account/rateLimits/read`，兼容旧 OAuth HTTP 响应；更新 JSBox 小组件使用新 HTTP 路径并保留旧路径回退；补充回归测试、说明文档并完成离线与只读集成验证。

## 2026-08-27 18:47:04 +08:00

- 用户：检查是否能获取 Codex 重置卡信息，并加入显示。
- 助手：确认 app-server 返回 `rateLimitResetCredits`，接入可用数量、最近到期时间和卡片标题解析；同步更新桌面弹窗、墨水屏标题行和 JSBox 小组件，不展示卡片 ID、不执行兑换。

## 2026-08-27 18:50:00 +08:00

- 用户：commit and push，并返回项目地址。
- 助手：已确认远程仓库为 `https://github.com/patdelphi/pat-quote0-burnout`，等待执行提交和推送前的最后确认。

## 2026-09-20 14:17:59 +0800

- 用户：参考 Rand/0 Display Mode 文档，为项目增加"完整 Display Mode"功能（200×200 布局 + 本地 WebSocket 推送，支持黑白 bw 与四级灰 gray4）。
- 助手：确认关键取舍（独立新文件、用 websocket-client 库、新建 200×200 布局）后实施：
  - 新增 `rand0_display.py`：200×200 渲染（bw/gray4）+ 位打包（bw 5000 字节、gray4 10000 字节）+ WebSocket 推送 + 按钮事件/错误处理 + 预览自检。
  - `display.py` 增加 `--display-mode <ip>` / `--gray4` 参数。
  - `requirements.txt` 增加 `websocket-client`（已安装 1.9.0）。
  - 新增 `tests/test_display_mode.py`：帧长度、位序、灰度量化、全黑/全白、推送 mock 测试，全部通过。
  - 文档：README 补用法，`docs/display-mode.md` 新增协议说明。
  - 累计 22 项测试全绿（含原有 tests/test_display.py）。

## 2026-09-20 14:40:00 +0800

- 用户：做一个本地窗口；询问 CLI 是否定时推送、一直运行还是一次性。
- 助手：说明 CLI 为一次性（外层 launchd 才做 5 分钟定时）；确认取舍后新增本地窗口：
  - 新增 `rand0_app.py`（tkinter）：IP 输入+保存到 .env、bw/gray4 选择、预览、推送、可选定时自动推送、设备消息日志区。
  - `rand0_display.py` 的 `push_frame` 增加 `on_message` 回调（GUI 展示设备消息），默认行为不变。
  - README 补窗口用法；冒烟测试验证 UI 构建与渲染显示链正常。
