# Codex 额度获取说明

## 当前实现

桌面程序默认启动本机 `codex app-server --stdio`，完成 JSON-RPC 握手后调用
`account/rateLimits/read`。这样由 Codex CLI 管理认证、刷新 token 和账户选择，程序不再直接依赖 `auth.json` 中的短期 access token。

app-server 返回的窗口字段为 `rateLimits.primary/secondary`，使用 camelCase：
`usedPercent`、`windowDurationMins`、`resetsAt`。

如果账户有可用重置卡，响应还会包含 `rateLimitResetCredits`。程序展示可用数量和最近一张卡的到期时间，不展示卡片 ID，也不会自动兑换。

## 兼容策略

如果找不到 Codex CLI、app-server 不可用或旧版 CLI 不支持该接口，Python 程序会回退到
`https://chatgpt.com/backend-api/codex/usage`，该路径返回旧式 `rate_limit` 结构时也能解析；新路径返回 404 时再尝试旧的 `wham/usage` 路径。

JSBox 小组件无法启动电脑上的本地 app-server，因此直接使用新的 HTTP 路径，并保留旧路径回退。
重置卡信息会同步显示在桌面弹窗、墨水屏标题行和 JSBox 小组件中。

## 配置

- `CODEX_COMMAND`：可选，自定义 Codex CLI 路径；默认从 PATH 查找 `codex`。
- `CODEX_ACCESS_TOKEN` / `CODEX_ACCOUNT_ID`：仅在 HTTP 回退时使用。

## 验证

离线回归测试位于 `tests/test_display.py`，覆盖 app-server 新结构、旧 HTTP 结构、缺失长窗口和 app-server 优先策略。
