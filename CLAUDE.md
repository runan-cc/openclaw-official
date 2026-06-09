# CLAUDE.md — OpenClaw (开物) Linux 便携版

## Project Overview

OpenClaw is an AI Gateway that aggregates multiple AI model providers (DeepSeek, Qwen, MiniMax, Kimi, GLM, Doubao, etc.) and chat channels (WeChat, WeCom, Feishu, DingTalk, QQ) behind a unified WebSocket API.

This directory is the **Linux portable edition** — zero-install, self-contained with bundled Node.js runtime.

- **Version:** 2026.6.1
- **Engine:** Node.js (openclaw npm package in `app/core/node_modules/openclaw/`)
- **Runtime:** Bundled Node.js 22.14.0 in `app/runtime/node-linux-x64/`
- **Stack:** Bash entry script + Python launcher + Python web server + HTML frontend

## Quick Start

```bash
./openclaw              # Open config page in browser
./openclaw webui        # Start Web UI on http://localhost:3131
./openclaw status       # Show system status
./openclaw gateway run  # Start the Gateway on port 18789
./openclaw help         # Full help
```

## Project Structure

```
openclaw-official/
├── openclaw              # Bash main entry point
├── launcher.py           # Python tkinter GUI launcher
├── lib/
│   ├── __init__.py
│   └── common.py         # Shared Python utilities
├── webui/
│   ├── server.py         # HTTP server (port 3131) — serves Control UI + Starter
│   └── starter.html      # Browser-based quick setup page
├── app/
│   ├── core/             # openclaw npm package (345 MB, 58 skills)
│   └── runtime/          # Bundled Node.js 22.14.0
├── data/.openclaw/       # Config, workspace, sessions, SQLite state
├── starter/              # Starter metadata
├── scripts/openclaw.service  # systemd unit
└── tests/                # pytest test suite
```

## Security Rules (CRITICAL)

- **NEVER** commit `data/.openclaw/` — contains secrets, private keys, session logs
- API keys go in environment variables or `data/.openclaw/openclaw.json` (gitignored)
- Gateway token: set via `OPENCLAW_GATEWAY_TOKEN` env var or config file
- Web server binds to `127.0.0.1` by default; use `--bind 0.0.0.0` only for trusted networks
- See `.gitignore` for full exclusion list

## Python Code Standards

- Follow PEP 8, type hints on all function signatures
- Shared utilities in `lib/common.py` — use them, don't duplicate
- Prefer specific exceptions over bare `except:`
- Use `logging` module, not `print()`
- Run `ruff check .` and `mypy lib/ launcher.py webui/server.py` before committing

## Testing

```bash
pytest --cov=lib --cov-report=term-missing
```

Target: 80%+ coverage on shared modules.

## Key Ports

| Port  | Service       | Default Bind |
|-------|---------------|-------------|
| 3131  | Web UI        | 127.0.0.1   |
| 18789 | Gateway       | 127.0.0.1   |

## Configuration

Main config: `data/.openclaw/openclaw.json`

Key sections:
- `models.providers` — AI model provider configs (api, apiKey, baseUrl, models)
- `gateway` — Gateway mode (local/remote), auth token
- `agents.defaults.model.primary` — Default AI model

## First-Time Setup

1. Run `./openclaw` to open the browser config page
2. Select a model provider and enter your API key
3. The config is saved automatically
4. Start the Gateway: `./openclaw gateway run`
5. Open Dashboard: http://127.0.0.1:18789
