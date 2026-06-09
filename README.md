OpenClaw (开物) Linux 便携版 — 一键启动，零安装

## 使用说明

```bash
./openclaw          # 一键启动 (自动打开浏览器 + 自动启动 Gateway)
./openclaw status   # 系统状态
```

浏览器打开 http://localhost:3131/starter → 配置模型 API Key → 完成

## 项目结构

```
openclaw-official/
├── openclaw                 # Bash 启动脚本
├── launcher.py              # Python GUI 启动器
├── webui/
│   ├── server.py            # Web 服务器 (端口 3131)
│   └── starter.html         # 浏览器快捷设置页面
├── lib/common.py            # 共享工具库
├── tests/                   # pytest 测试
├── app/
│   ├── core/                # OpenClaw 引擎 (Node.js)
│   └── runtime/             # 捆绑 Node.js 运行时
└── data/.openclaw/          # 运行时数据 (已 gitignore)
```

## 依赖

- Python 3.10+
- Node.js >= 22.19 (优先系统 node，fallback bundled)

## 安全

- `data/.openclaw/` 已加入 .gitignore
- API Key 通过配置页面设置，不硬编码在代码中
- Web 服务器默认绑定 127.0.0.1