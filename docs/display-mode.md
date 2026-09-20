# Rand/0 Display Mode 推送

通过本地 WebSocket 把 AI 额度仪表盘推送到 MindReset **Rand/0** 设备的 Display Mode。

## 参考

- 官方文档：https://dot.mindreset.tech/docs/rand_0/start/features/display_mode
- 官方实现：https://github.com/MindReset/dot_open_platform/tree/main/capabilities/rand_0_display_mode
- 协议版本：Rand/0 firmware `1.3.1`

## 与 Quote/0 云端推送的区别

| 维度 | 本功能（Display Mode） | 现有墨水屏推送 |
|------|------------------------|----------------|
| 设备 | Rand/0 | Quote/0 |
| 分辨率 | 200×200 | 296×152 |
| 传输 | 本地 WebSocket（`ws://<IP>/display/…`） | 云端 HTTPS API |
| 认证 | 无（仅限可信局域网） | API Key |
| 像素格式 | 黑白 1bit / 四级灰 2bit | 纯黑白 PNG |

## 协议要点

| 端点 | 帧长度 | 格式 |
|------|--------|------|
| `ws://<IP>/display/bw` | 恰好 5000 字节 | 1 bit/像素，黑白 |
| `ws://<IP>/display/gray4` | 恰好 10000 字节 | 2 bit/像素，四级灰 |

- 行主序，从左到右、从上到下；**最高位代表最左像素**。
- 黑白：`1=白` `0=黑`；首像素用 bit7。
- 四级灰：`00=白 01=浅灰 10=深灰 11=黑`；首像素用 bit7-6。
- 一次发送一个二进制帧；设备回传按钮事件/错误为文本 JSON，例如
  `{"type":"key","key":"up","action":"short"}`。
- 同一时刻仅一个客户端激活，新连接替换旧连接。

## 使用

设备侧：
1. 进入 **Main menu → More → Display**。
2. 等设备显示本地 IP；确保与电脑同一局域网、电量充足或接电。

电脑侧（依赖 `websocket-client`）：

```bash
# 黑白推送到 192.168.1.100
python display.py --display-mode 192.168.1.100

# 四级灰
python display.py --display-mode 192.168.1.100 --gray4

# 本地预览 200×200 布局（不推送）
python rand0_display.py --preview --mode bw
python rand0_display.py --preview --mode gray4
```

## 代码结构

- `rand0_display.py` —— 独立模块
  - `render_frame(snapshot, mode)`：渲染 200×200 并打包为二进制帧（5000/10000 字节）
  - `push_frame(ip, mode, payload, timeout)`：WebSocket 推送，监听按钮事件/错误
- `display.py` —— CLI 接入：`--display-mode <ip>`、`--gray4`

## 常见设备错误

| 错误 | 含义 |
|------|------|
| `expected_binary_5000` / `expected_binary_10000` | 帧类型或长度不对（本模块已校验） |
| `inactive_client` | 连接未被设备识别，重发或重连 |
| `no_memory` / `queue_busy` | 显示刷新中，稍后重发最新帧 |
| `WebSocket failed to start` | 重启设备并重进 Display Mode |

## 验证

`tests/test_display_mode.py` 覆盖：帧长度（5000/10000）、位序（首像素 bit7 / bit7-6）、灰度量化、全黑/全白、WebSocket 推送逻辑（mock）。

```bash
python -m pytest tests/test_display_mode.py
```