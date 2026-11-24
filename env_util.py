"""环境配置工具：确保同目录存在 .env 与 .env.sample 模板。

供 local_app.py / rand0_app.py 复用。首次运行若无 .env，则：
- 自动创建 .env（内置模板，填充占位值，用户可编辑）
- 同时生成 .env.sample 模板文件供参考
模板内置于代码，不依赖外部文件，便于 PyInstaller 打包后使用。
"""

from __future__ import annotations

from pathlib import Path

# 内置 .env 模板（覆盖本地弹窗 + Rand/0 Display Mode 全部配置）
ENV_TEMPLATE = """\
# DeepSeek API Key（必填）
export DEEPSEEK_API_KEY="sk-xxx"

# Codex 额度（默认调用本机 Codex app-server，自动使用 Codex CLI 的登录状态）
# 如未安装 Codex CLI，才需要通过 OAuth HTTP 回退接口提供 token
# export CODEX_COMMAND=""
# export CODEX_ACCESS_TOKEN=""
# export CODEX_ACCOUNT_ID=""

# 本地弹窗配置
export REFRESH_INTERVAL=300    # 刷新间隔（秒），默认 5 分钟
export WINDOW_OPACITY=0.92     # 窗口不透明度 0.0-1.0，默认 0.92

# 字体配置（全部从 .env 读取，不硬编码）
export FONT_FAMILY="Arial"           # 字体名称：Arial / Consolas / 微软雅黑 / 等线
export FONT_SIZE=10                  # 基础字号（px），默认 10
export FONT_SIZE_LARGE_OFFSET=0      # 余额等大字的字号增量，设为 0 则全部统一大小

# Rand/0 Display Mode 窗口配置（可由窗口内的操作自动写入，也可手动填写）
# export RAND0_IP=""                       # 设备本地 IP（进入 Display Mode 后显示）
# export RAND0_MODE="bw"                   # 默认显示模式：bw 黑白 / gray4 四级灰
# export RAND0_INVERT=0                    # 是否反显：0 白底黑字 / 1 黑底白字
# export RAND0_INTERVAL=0                  # 自动推送间隔（分钟）：0=关闭定时推送，正整数=每 N 分钟推送
# export RAND0_TIMEOUT="5"                 # WebSocket 连接/收发超时（秒）

# ESP32-S3 RLCD 无线投屏自动推送配置（推送到 xiaozhi-esp32 cast_server）
export RLCD_CAST_ENABLED=0                         # 开关：0=关闭（默认），1=开启自动推送
export RLCD_CAST_URL="http://127.0.0.1:8787/push"  # 无线投屏后台 /push 地址（支持仅填根地址）
export RLCD_CAST_WIDTH=400                         # 渲染宽度（默认 400）
export RLCD_CAST_HEIGHT=300                        # 渲染高度（默认 300）
export RLCD_CAST_TEMPLATE="sync"                   # 模板：sync 跟随窗口 / bar 进度条 / ring 圆环
export RLCD_CAST_INVERT=0                          # 是否反显：0 白底黑字 / 1 黑底白字
export RLCD_CAST_PUSH_NOW=1                        # 推送时附带 push_now=1 立即刷屏
export RLCD_CAST_TIMEOUT=5                         # HTTP 推送超时（秒）
"""


def ensure_env(config_dir: Path) -> Path:
    """确保 config_dir 下存在 .env；无则创建 .env 并生成 .env.sample 模板。

    返回 .env 路径。
    """
    env_path = config_dir / ".env"
    sample_path = config_dir / ".env.sample"

    if not env_path.exists():
        env_path.write_text(ENV_TEMPLATE, encoding="utf-8")

    if not sample_path.exists():
        sample_path.write_text(ENV_TEMPLATE, encoding="utf-8")

    return env_path