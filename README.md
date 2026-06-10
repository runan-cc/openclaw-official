OpenClaw（开物）— 多平台 AI 网关

一个聚合多种 AI 模型和聊天平台的网关，支持 DeepSeek、通义千问、MiniMax 等模型 + 微信、飞书、钉钉、QQ 等通道。

跨平台使用，零依赖安装，Python 3.9+ 和 Node.js ≥22 即可运行。

## 快速上手

```bash
# Linux / macOS — 终端启动
./openclaw               # 打开浏览器配置页面
./openclaw status        # 查看系统状态
./openclaw help          # 完整帮助

# Windows — 双击 openclaw.bat
```

浏览器打开 http://localhost:3131/starter → 选择模型 → 填入 API Key → 完成配置。

## 命令一览

| 命令 | 说明 |
|------|------|
| `./openclaw` | 打开浏览器配置页面 |
| `./openclaw webui [端口]` | 启动 Web 管理界面（默认 3131） |
| `./openclaw status` | 查看系统状态 |
| `./openclaw gateway run` | 启动 AI 网关服务 |
| `./openclaw help` | 完整帮助 |

## 支持的平台

| 平台 | 入口 | 终端打开方式 |
|------|------|-------------|
| 🐧 Linux | `./openclaw` | 自动检测 gnome-terminal、konsole、ptyxis 等 |
| 🖥️ Windows | `openclaw.bat` | 自动打开 cmd |
| 🍎 macOS | `./openclaw` 或 `openclaw.command` | 自动打开 Terminal.app |

桌面 GUI 启动器：`python3 launcher.py`

## 依赖

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | ≥ 3.9 | 纯标准库，零 pip 安装 |
| Node.js | ≥ 22 | 优先用系统安装的 node，没有则用 bundled runtime |

## 项目结构

```
openclaw-official/
├── openclaw            # Linux/macOS 启动脚本
├── openclaw.bat        # Windows 启动脚本
├── openclaw.command    # macOS 双击启动
├── launcher.py         # 跨平台 GUI 启动器
├── webui/
│   ├── server.py       # Web 服务器 (端口 3131)
│   └── starter.html    # 浏览器配置页面
├── lib/common.py       # 共享工具库
├── tests/              # pytest 测试
├── app/
│   ├── core/           # OpenClaw 引擎 (Node.js npm 包)
│   └── runtime/        # 各平台捆绑 Node.js 运行时
└── data/.openclaw/     # 运行时数据 (已 gitignore)
```

## 安全

- `data/.openclaw/` 已加入 .gitignore，不会被提交
- API Key 通过配置页面设置，不硬编码在代码中
- Web 服务器默认绑定 127.0.0.1，仅本地访问

## 测试

```bash
pytest tests/ --cov=lib --cov-report=term-missing
```

## 免责声明

OpenClaw 是一款开源工具，遵循 MIT 协议。使用者应确保所接入的第三方服务符合其服务条款。AI 生成的内容可能存在错误，请自行判断和核实。
