# Chat History

## 2026-08-27 18:35:39 +08:00

- 用户：修改代码，适配 Codex 新的额度获取方式。
- 助手：将 Python 默认额度来源改为 Codex CLI app-server 的 `account/rateLimits/read`，兼容旧 OAuth HTTP 响应；更新 JSBox 小组件使用新 HTTP 路径并保留旧路径回退；补充回归测试、说明文档并完成离线与只读集成验证。

## 2026-08-27 18:47:04 +08:00

- 用户：检查是否能获取 Codex 重置卡信息，并加入显示。
- 助手：确认 app-server 返回 `rateLimitResetCredits`，接入可用数量、最近到期时间和卡片标题解析；同步更新桌面弹窗、墨水屏标题行和 JSBox 小组件，不展示卡片 ID、不执行兑换。

## 2026-08-27 18:50:00 +08:00

- 用户：commit and push，并返回项目地址。
- 助手：已确认远程仓库为 `https://github.com/patdelphi/pat-quote0-burnout`，等待执行提交和推送前的最后确认。
