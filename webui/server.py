#!/usr/bin/env python3
"""OpenClaw Web UI Server — serves Control UI + Starter with auto-config"""
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT: Path
try:
    ROOT = Path(__file__).resolve().parent.parent
except NameError:
    ROOT = Path().resolve()
if not ROOT or not (ROOT / "openclaw").exists():
    cwd = Path().resolve()
    for p in [cwd] + list(cwd.parents):
        if (p / "openclaw").exists():
            ROOT = p
            break

# Ensure lib/ is importable regardless of CWD
sys.path.insert(0, str(ROOT))

CONTROL_UI = ROOT / "app" / "core" / "node_modules" / "openclaw" / "dist" / "control-ui"
WEBUI_DIR = Path(__file__).parent
GW_PORT = 18789
GW_HOST = "127.0.0.1"
DEFAULT_BIND = "127.0.0.1"
ENGINE_MJS = ROOT / "app" / "core" / "node_modules" / "openclaw" / "openclaw.mjs"
DATA_HOME = ROOT / "data" / ".openclaw"
NODE = "node"
# Prefer system node (may be newer than bundled), fall back to platform-matched runtime
system_node = shutil.which("node")
if system_node:
    NODE = system_node
else:
    try:
        from lib.common import get_node_binary
        NODE = get_node_binary(ROOT)
    except ImportError:
        NODE = "node"
LOG_FILE = ROOT / "data" / ".openclaw" / "logs" / "gateway.log"
GW_REAL_LOG = ROOT / "data" / ".openclaw" / ".openclaw" / "logs"  # gateway log directory

# In-memory state for async plugin installs and channel logins
_plugin_processes: dict[str, subprocess.Popen] = {}

# Track running plugin install processes (plugin-id → Popen)
_plugin_processes: dict[str, subprocess.Popen] = {}

# Read auto token from config or env var, never hardcoded
def _get_gateway_token(config_path: Path) -> str:
    """Read gateway token from config, env var, or generate a random one."""
    # Priority: env var > config file > random generation
    env_token = os.environ.get("OPENCLAW_GATEWAY_TOKEN")
    if env_token:
        return env_token
    try:
        cfg = json.loads(config_path.read_text())
        cfg_token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
        if cfg_token:
            return cfg_token
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # Generate a random token and warn
    random_token = secrets.token_urlsafe(32)
    print(f"[WARN] No gateway token configured. Generated: {random_token}", file=sys.stderr)
    print("[INFO] Set OPENCLAW_GATEWAY_TOKEN env var or configure via the starter page.", file=sys.stderr)
    return random_token

# Read gateway auth mode from config
def _get_gateway_auth_mode(config_path: Path) -> str:
    try:
        cfg = json.loads(config_path.read_text())
        return cfg.get("gateway", {}).get("auth", {}).get("mode", "token")
    except (FileNotFoundError, json.JSONDecodeError):
        return "token"

AUTH_MODE = _get_gateway_auth_mode(ROOT / "data" / ".openclaw" / "openclaw.json")
AUTO_TOKEN = _get_gateway_token(ROOT / "data" / ".openclaw" / "openclaw.json")

# ALWAYS sync the token to config so Gateway and Control UI match
def _sync_gateway_token():
    try:
        p = ROOT / "data" / ".openclaw" / "openclaw.json"
        cfg = json.loads(p.read_text())
        changed = False
        if "gateway" not in cfg:
            cfg["gateway"] = {}
            changed = True
        if "auth" not in cfg["gateway"]:
            cfg["gateway"]["auth"] = {}
            changed = True
        if cfg["gateway"].get("mode") != "local":
            cfg["gateway"]["mode"] = "local"
            changed = True
        if cfg["gateway"]["auth"].get("mode") != "token":
            cfg["gateway"]["auth"]["mode"] = "token"
            changed = True
        if cfg["gateway"]["auth"].get("token") != AUTO_TOKEN:
            cfg["gateway"]["auth"]["token"] = AUTO_TOKEN
            changed = True
        if changed:
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            print(f"[INFO] Gateway token synced to config", file=sys.stderr)
    except Exception:
        pass

_sync_gateway_token()


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base, returning a new dict.

    Values from overlay win. Nested dicts are merged; everything else is replaced.
    This preserves top-level keys (logging, plugins, devices, etc.) that the
    starter frontend doesn't know about.
    """
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

# Pre-compute the localStorage injection script
INJECT_SCRIPT = f"""
<script>
(function(){{
  var gatewayUrl = 'ws://{GW_HOST}:{GW_PORT}';
  var token = '{AUTO_TOKEN}';
  var authMode = '{AUTH_MODE}';
  var settingsKey = 'openclaw.control.settings.v1';
  var tokenKey = 'openclaw.control.token.v1:' + gatewayUrl;

  // When auth is disabled, don't set a token
  if (authMode !== 'none') {{
    try {{ localStorage.setItem(tokenKey, token); }} catch(e){{}}
  }} else {{
    try {{ localStorage.removeItem(tokenKey); }} catch(e){{}}
  }}

  // Pre-set settings (auto-connect)
  var settings = {{
    gatewayUrl: gatewayUrl,
    token: authMode === 'none' ? '' : token,
    sessionKey: 'main',
    lastActiveSessionKey: 'main',
    theme: 'claw',
    themeMode: 'dark',
    chatShowThinking: true,
    chatShowToolCalls: true,
    chatAutoScroll: 'near-bottom',
    splitRatio: 0.6,
    navCollapsed: false,
    navWidth: 258,
    navGroupsCollapsed: {{}},
    recentSessionsCollapsed: false,
    borderRadius: 50,
    textScale: 100
  }};
  // Clean any stale localStorage settings that might block auto-connect
  try {{ localStorage.removeItem(settingsKey); }} catch(e){{}}
  try {{ localStorage.removeItem('openclaw.control.settings.v1:default'); }} catch(e){{}}
  // Write fresh settings
  try {{
    localStorage.setItem(settingsKey, JSON.stringify(settings));
    localStorage.setItem('openclaw.control.settings.v1:default', JSON.stringify(settings));
  }} catch(e){{}}

  // Auto-click connect button after page loads (retry if React not ready)
  var attempts = 0;
  function tryConnect() {{
    var urlInput = document.querySelector('.login-gate__form input[placeholder*=\"ws://\"]');
    var tokenInput = document.querySelector('.login-gate__form input[placeholder*=\"OPENCLAW_GATEWAY_TOKEN\"]') || document.querySelector('.login-gate__form input[type=\"password\"]');
    if (urlInput && tokenInput) {{
      urlInput.value = gatewayUrl;
      tokenInput.value = token;
      var connectBtn = document.querySelector('.login-gate__connect, button.primary');
      if (connectBtn) {{
        connectBtn.click();
        return;
      }}
    }}
    attempts++;
    if (attempts < 20) setTimeout(tryConnect, 500);
  }}
  setTimeout(tryConnect, 800);
}})();
</script>
"""

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, directory=str(CONTROL_UI), **kw)

    def do_GET(self) -> None:
        if self.path == "/starter" or self.path == "/config" or self.path == "/settings":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write((WEBUI_DIR / "starter.html").read_bytes())
            return
        if self.path == "/api/status":
            return self._json(self._get_status())
        if self.path == "/api/logs":
            return self._json(self._get_logs())
        if self.path.startswith("/api/which"):
            cmd = self.path.split("=", 1)[-1] if "=" in self.path else ""
            return self._json({"found": bool(cmd and shutil.which(cmd))})
        if self.path == "/api/config":
            return self._json(self._load_config())
        if self.path.startswith("/api/channels/login-status"):
            qrcode = self.path.split("=", 1)[-1] if "=" in self.path else ""
            return self._json(self._get_weixin_login_status(qrcode))
        if self.path == "/api/auto-token":
            return self._json({"token": AUTO_TOKEN, "gatewayUrl": f"ws://{GW_HOST}:{GW_PORT}"})
        if self.path == "/api/gateway/health":
            return self._json(self._gateway_health())
        if self.path == "/api/gateway/restart":
            return self._json(self._restart_gateway())
        if self.path == "/api/update/check":
            return self._json(self._update_check())
        if self.path == "/api/update/run":
            return self._json(self._update_run())
        if self.path == "/api/terminal":
            return self._json(self._open_terminal())
        if self.path == "/" or self.path == "" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            html = (CONTROL_UI / "index.html").read_bytes()
            # Inject auto-config script before </body> (more robust than </head>)
            html = html.replace(b"</body>", INJECT_SCRIPT.encode() + b"</body>")
            self.wfile.write(html)
            return

        return super().do_GET()

    def do_POST(self) -> None:
        try:
            body = self._read()
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "Invalid request body"}, 400)
            return
        if self.path == "/api/config":
            self._save_config(body)
            return self._json({"ok": True})
        if self.path == "/api/plugins/install":
            plugin_id = body.get("plugin", "")
            if not plugin_id:
                return self._json({"error": "Missing plugin id"}, 400)
            return self._json(self._install_plugin(plugin_id))
        if self.path == "/api/plugins/status":
            plugin_id = body.get("plugin", "")
            if not plugin_id:
                return self._json({"error": "Missing plugin id"}, 400)
            return self._json(self._plugin_status(plugin_id))
        if self.path == "/api/channels/unbind":
            channel_id = body.get("channel", "")
            if not channel_id:
                return self._json({"error": "Missing channel"}, 400)
            return self._json(self._unbind_channel(channel_id))
        if self.path == "/api/channels/login":
            channel = body.get("channel", "")
            if not channel:
                return self._json({"error": "Missing channel"}, 400)
            return self._json(self._auto_login(channel, body.get("npm", body.get("npmSpec", ""))))
        if self.path == "/api/channels/token":
            channel = body.get("channel", "")
            token = body.get("token", "")
            if not channel or not token:
                return self._json({"error": "Missing channel or token"}, 400)
            return self._json(self._channel_token_setup(channel, body.get("npm", ""), token))
        if self.path == "/api/channels/feishu":
            channel = body.get("channel", "")
            app_id = body.get("appId", "")
            app_secret = body.get("appSecret", "")
            if not channel or not app_id or not app_secret:
                return self._json({"error": "Missing channel, appId or appSecret"}, 400)
            return self._json(self._channel_feishu_setup(channel, body.get("npm", ""), app_id, app_secret))
        if self.path == "/api/channels/dingtalk":
            channel = body.get("channel", "")
            app_id = body.get("appId", "")
            app_secret = body.get("appSecret", "")
            if not channel or not app_id or not app_secret:
                return self._json({"error": "Missing channel, appId or appSecret"}, 400)
            return self._json(self._channel_dingtalk_setup(channel, body.get("npm", ""), app_id, app_secret))
        if self.path == "/api/channels/qqbot":
            channel = body.get("channel", "")
            app_id = body.get("appId", "")
            app_secret = body.get("appSecret", "")
            if not channel or not app_id or not app_secret:
                return self._json({"error": "Missing channel, appId or appSecret"}, 400)
            return self._json(self._channel_qqbot_setup(channel, body.get("npm", ""), app_id, app_secret))
        if self.path == "/api/gateway/start":
            return self._json(self._start_gateway())
        if self.path == "/api/gateway/stop":
            return self._json(self._stop_gateway())
        if self.path == "/api/gateway/restart":
            return self._json(self._restart_gateway())
        if self.path == "/api/update/check":
            return self._json(self._update_check())
        if self.path == "/api/update/run":
            return self._json(self._update_run())
        self._json({"error": "Not found"}, 404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", f"http://localhost:{self.server.server_address[1]}")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, data: dict, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", f"http://localhost:{self.server.server_address[1]}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length > 1_048_576:  # 1 MB limit
            raise ValueError("Request body too large")
        return json.loads(self.rfile.read(length)) if length else {}

    def _load_config(self) -> dict:
        try:
            return json.loads((ROOT / "data" / ".openclaw" / "openclaw.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _gateway_health(self) -> dict:
        """Proxy check of Gateway health (avoids browser CORS issues)."""
        try:
            import urllib.request
            req = urllib.request.Request(f"http://{GW_HOST}:{GW_PORT}/health", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                return {"ok": True, "gateway": data}
        except Exception:
            return {"ok": False, "gateway": {"status": "offline"}}

    def _get_status(self) -> dict:
        node_ok, node_ver = False, "?"
        try:
            r = subprocess.run([NODE, "--version"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                node_ok, node_ver = True, r.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        ed = ROOT / "app" / "core" / "node_modules" / "openclaw"
        eng_ok = ed.exists()
        eng_ver = "?"
        if eng_ok:
            try:
                eng_ver = json.loads((ed / "package.json").read_text()).get("version", "?")
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        ws = ROOT / "data" / ".openclaw" / "workspace"
        ws_files = [f.name for f in ws.glob("*.md")] if ws.exists() else []
        cfg = self._load_config()
        # Check if ANY provider has a configured API key (not just deepseek)
        providers = cfg.get("models", {}).get("providers", {})
        has_api_key = any(
            p.get("apiKey", "") and not p.get("apiKey", "").startswith("YOUR")
            for p in providers.values()
        )
        skills = len(list(ed.glob("skills/*"))) if ed.exists() else 0
        return {"status": "running", "node": {"installed": node_ok, "version": node_ver},
                "engine": {"installed": eng_ok, "version": eng_ver, "skills": skills},
                "workspace": {"files": ws_files},
                "config": {"has_api_key": has_api_key,
                           "model": cfg.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "?")}}

    def _get_logs(self) -> dict:
        # Check both locations: the expected LOG_FILE and the real Gateway log dir
        log_files: list[Path] = []
        if LOG_FILE.exists():
            log_files.append(LOG_FILE)
        if GW_REAL_LOG.exists():
            log_files.extend(sorted(GW_REAL_LOG.glob("openclaw-*.log"), reverse=True))
        for lf in log_files:
            if not lf.exists():
                continue
            try:
                raw = lf.read_text(errors="replace")[-5000:]
                # Gateway logs are JSONL — extract just the "message" field for readability
                lines = []
                for line in raw.strip().split("\n"):
                    try:
                        obj = json.loads(line)
                        msg = obj.get("message", "")
                        ts = obj.get("time", "")[-15:] if "time" in obj else ""
                        if ts:
                            lines.append(f"[{ts}] {msg}")
                        else:
                            lines.append(msg)
                    except (json.JSONDecodeError, TypeError):
                        lines.append(line[:200])
                return {"logs": "\n".join(lines) if lines else raw[-5000:]}
            except (OSError, PermissionError):
                continue
        return {"logs": "Gateway 尚未启动或无日志"}

    def _save_config(self, cfg: dict) -> None:
        p = ROOT / "data" / ".openclaw" / "openclaw.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Deep merge the incoming config with existing config to avoid data loss
        existing = self._load_config()
        merged = _deep_merge(existing, cfg)
        # Always keep gateway auth minimal — token injected at startup
        if "gateway" not in merged:
            merged["gateway"] = {}
        merged["gateway"]["mode"] = "local"
        if "auth" not in merged["gateway"]:
            merged["gateway"]["auth"] = {}
        merged["gateway"]["auth"]["mode"] = "none"
        if "token" in merged["gateway"]["auth"]:
            del merged["gateway"]["auth"]["token"]
        # Ensure saved model entries have required fields
        for provider_key, provider in merged.get("models", {}).get("providers", {}).items():
            for model in provider.get("models", []):
                if "contextWindow" not in model:
                    model["contextWindow"] = 128000
                if "cost" not in model:
                    model["cost"] = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
        p.write_text(json.dumps(merged, indent=2, ensure_ascii=False))

    def log_message(self, fmt: str, *args) -> None:
        """Log HTTP requests to stderr for debuggability."""
        sys.stderr.write(f"[HTTP] {self.address_string()} - {fmt % args}\n")

    def _start_gateway(self) -> dict:
        """Start Gateway as a background subprocess and return status."""
        try:
            env = os.environ.copy()
            env["OPENCLAW_HOME"] = str(DATA_HOME)
            env["OPENCLAW_STATE_DIR"] = str(DATA_HOME / ".openclaw")
            env["OPENCLAW_NO_AUTO_UPDATE"] = "true"
            proc = subprocess.Popen(
                [NODE, str(ENGINE_MJS), "gateway", "run"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=env, cwd=str(ROOT))
            _plugin_processes["gateway"] = proc
            return {"ok": True, "message": "Gateway started", "pid": proc.pid}
        except (FileNotFoundError, OSError) as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _find_pid_by_port(port: int) -> int | None:
        """Find the PID of a process listening on a given TCP port via /proc."""
        import re
        try:
            with open("/proc/net/tcp") as f:
                next(f)  # skip header line
                for line in f:
                    parts = line.strip().split()
                    if len(parts) < 10:
                        continue
                    # Local address is field 2 (hex IP:hex port)
                    local = parts[1]
                    hex_port = local.split(":")[-1]
                    if int(hex_port, 16) == port:
                        # inode is field 10
                        inode = parts[9]
                        # Find the PID by scanning /proc/*/fd/*
                        for pid_dir in Path("/proc").iterdir():
                            if not pid_dir.name.isdigit():
                                continue
                            try:
                                for fd in (pid_dir / "fd").iterdir():
                                    link = os.readlink(str(fd))
                                    if f"socket:[{inode}]" == link:
                                        return int(pid_dir.name)
                            except (OSError, PermissionError):
                                continue
            return None
        except (OSError, PermissionError):
            return None

    def _stop_gateway(self) -> dict:
        """Stop the Gateway process."""
        import signal
        killed = False

        # 1. Try the in-memory Popen reference first
        proc = _plugin_processes.get("gateway")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            _plugin_processes.pop("gateway", None)
            killed = True

        # 2. Fallback: kill any process still listening on the gateway port
        pid = self._find_pid_by_port(18789)
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
                killed = True
            except (OSError, PermissionError):
                pass

        if killed:
            return {"ok": True, "message": "Gateway stopped"}
        return {"ok": True, "message": "Gateway was not running"}

    def _restart_gateway(self) -> dict:
        """Restart the Gateway subprocess."""
        self._stop_gateway()
        time.sleep(1)
        return self._start_gateway()

    def _resolve_npm(self) -> list[str]:
        """Resolve npm as a [node, path] pair using the bundled runtime.
        npm is just a Node.js script — no separate install needed."""
        node_bin = NODE  # already resolved at startup
        candidates = [
            # Linux
            str(ROOT / "app" / "runtime" / "node-linux-x64" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"),
            str(ROOT / "app" / "runtime" / "node-linux-arm64" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"),
            # macOS
            str(ROOT / "app" / "runtime" / "node-darwin-x64" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"),
            str(ROOT / "app" / "runtime" / "node-darwin-arm64" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"),
            # Windows
            str(ROOT / "app" / "runtime" / "node-win-x64" / "node_modules" / "npm" / "bin" / "npm-cli.js"),
            str(ROOT / "app" / "runtime" / "node-win-arm64" / "node_modules" / "npm" / "bin" / "npm-cli.js"),
        ]
        for p in candidates:
            if Path(p).exists():
                return [node_bin, p]
        # Fallback: trust system npm
        system_npm = shutil.which("npm")
        if system_npm:
            return [system_npm]
        return ["npm"]

    def _update_check(self) -> dict:
        """Check for available npm updates."""
        try:
            pkg = json.loads((ENGINE_DIR / "package.json").read_text())
            current = pkg.get("version", "?")
            npm = self._resolve_npm()
            r = subprocess.run(
                npm + ["view", "openclaw", "version"],
                capture_output=True, text=True, timeout=15,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
                cwd=str(ROOT))
            latest = r.stdout.strip() if r.returncode == 0 else current
            has_update = latest != current and latest != "?"
            return {
                "ok": True,
                "current": current,
                "latest": latest,
                "hasUpdate": has_update,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _update_run(self) -> dict:
        """Run npm install to update the OpenClaw package (self-contained)."""
        core_dir = ROOT / "app" / "core"
        try:
            self._stop_gateway()
            time.sleep(0.5)
            npm = self._resolve_npm()
            r = subprocess.run(
                npm + ["install", "openclaw@latest"],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, "PATH": os.environ.get("PATH", "")},
                cwd=str(core_dir))
            if r.returncode == 0:
                return {"ok": True, "message": "更新完成，请重启 Gateway"}
            else:
                return {"ok": False, "error": r.stderr[-500:] or "npm install failed"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "更新超时，请手动运行: cd app/core && npm install openclaw@latest"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _open_terminal(self) -> dict:
        """Detect available terminal emulator and open it at the project root."""
        import platform
        import shutil

        system = platform.system()

        if system == "Windows":
            try:
                subprocess.Popen(
                    ["cmd", "/c", "start", "cmd", "/K", f"cd /d {ROOT} && echo *** OpenClaw CLI ***"],
                    start_new_session=True,
                )
                return {"ok": True, "terminal": "cmd.exe"}
            except (FileNotFoundError, OSError) as e:
                return {"ok": False, "error": str(e)}

        if system == "Darwin":
            try:
                subprocess.Popen(
                    ["open", "-a", "Terminal", str(ROOT)],
                    start_new_session=True,
                )
                return {"ok": True, "terminal": "Terminal.app"}
            except (FileNotFoundError, OSError):
                pass
            try:
                subprocess.Popen(
                    ["osascript", "-e",
                     f'tell app "Terminal" to do script "cd {ROOT}"'],
                    start_new_session=True,
                )
                return {"ok": True, "terminal": "Terminal.app"}
            except (FileNotFoundError, OSError) as e:
                return {"ok": False, "error": str(e)}

        # Linux
        candidates = [
            ("ptyxis", ["ptyxis", "--"]),
            ("gnome-terminal", ["gnome-terminal", "--"]),
            ("xfce4-terminal", ["xfce4-terminal", "-x"]),
            ("lxterminal", ["lxterminal", "-e"]),
            ("konsole", ["konsole", "-e"]),
            ("tilix", ["tilix", "-e"]),
            ("terminator", ["terminator", "-e"]),
            ("x-terminal-emulator", ["x-terminal-emulator", "-x"]),
            ("xterm", ["xterm", "-e"]),
            ("urxvt", ["urxvt", "-e"]),
        ]
        shell_cmd = f"cd {ROOT} && echo -e '\\033[36m~~~ OpenClaw CLI ~~~\\033[0m'; exec bash"
        for name, tmpl in candidates:
            if not shutil.which(name):
                continue
            try:
                env = os.environ.copy()
                for k in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
                    if k in os.environ:
                        env[k] = os.environ[k]
                subprocess.Popen(tmpl + ["bash", "-c", shell_cmd], env=env, start_new_session=True)
                return {"ok": True, "terminal": name}
            except (FileNotFoundError, OSError):
                continue
        return {"ok": False, "error": "No supported terminal found"}

    def _install_plugin(self, plugin_id: str) -> dict:
        """Install a plugin via the OpenClaw CLI. Runs asynchronously."""
        if not ENGINE_MJS.exists():
            return {"ok": False, "error": "OpenClaw engine not found"}
        # Check if already running
        if plugin_id in _plugin_processes:
            proc = _plugin_processes[plugin_id]
            if proc.poll() is None:
                return {"ok": True, "status": "installing", "message": f"{plugin_id} 正在安装中..."}
        try:
            env = os.environ.copy()
            env["OPENCLAW_HOME"] = str(DATA_HOME)
            env["OPENCLAW_STATE_DIR"] = str(DATA_HOME / ".openclaw")
            env["OPENCLAW_NO_AUTO_UPDATE"] = "true"
            # Use --force to handle "already exists" gracefully
            proc = subprocess.Popen(
                [NODE, str(ENGINE_MJS), "plugins", "install", plugin_id, "--force"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env, cwd=str(ROOT))
            _plugin_processes[plugin_id] = proc
            return {"ok": True, "status": "started", "message": f"开始安装 {plugin_id}..."}
        except (FileNotFoundError, OSError) as e:
            return {"ok": False, "error": str(e)}

    def _auto_login(self, channel_id: str, npm_spec: str) -> dict:
        """Full auto channel setup: ensure plugin installed, get QR code.

        For Weixin: calls the ilink API to get a QR code.  After returning the
        QR URL to the browser we continue polling ilink in the background until
        the user scans with WeChat, then save the resulting bot_token to the
        Gateway channel config so the channel is ready to use.
        """
        result: dict = {"ok": True, "status": "qr_ready", "qrUrl": "", "message": ""}

        # Step 1: Ensure plugin is installed
        installed = self._check_plugin_installed(npm_spec)
        if not installed:
            self._install_plugin(npm_spec)
            for _ in range(30):
                time.sleep(2)
                if self._check_plugin_installed(npm_spec):
                    break
            installed = self._check_plugin_installed(npm_spec)
            if not installed:
                result["status"] = "installing"
                result["message"] = f"{channel_id} 插件安装中，请稍后重试"
                return result

        # Step 2: Get QR code
        if channel_id == "openclaw-weixin":
            qr = self._get_weixin_qr()
            if qr.get("qrUrl"):
                result.update(qr)
                # Step 3: Background polling for scan confirmation → save bot_token
                threading.Thread(
                    target=self._poll_weixin_login,
                    args=(qr["qrcode"], channel_id),
                    daemon=True,
                ).start()
                return result
            result["status"] = "error"
            result["message"] = qr.get("error", "获取二维码失败")
            return result

        # Other channels: return url for user to configure manually
        result["message"] = f"请在终端运行: openclaw channels login --channel {channel_id}"
        return result

    def _poll_weixin_login(self, qrcode: str, channel_id: str) -> None:
        """Background thread: poll ilink until user scans QR, then save bot token."""
        import urllib.request, urllib.error
        api_base = "https://ilinkai.weixin.qq.com"
        deadline = time.time() + 480  # 8 min timeout
        verify_code = None
        while time.time() < deadline:
            try:
                endpoint = f"ilink/bot/get_qrcode_status?qrcode={qrcode}"
                if verify_code:
                    endpoint += f"&verify_code={verify_code}"
                req = urllib.request.Request(
                    f"{api_base}/{endpoint}", method="GET",
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=35) as resp:
                    data = json.loads(resp.read().decode())
                status = data.get("status", "")
                if status == "confirmed":
                    bot_token = data.get("bot_token")
                    ilink_bot_id = data.get("ilink_bot_id")
                    if bot_token and ilink_bot_id:
                        self._save_weixin_credential(channel_id, ilink_bot_id, bot_token)
                    return
                elif status == "need_verifycode":
                    verify_code = None  # user types in terminal; we skip for now
                elif status == "expired":
                    return  # QR expired, user needs to request a new one
                # "wait" / "scaned" / "scaned_but_redirect" — keep polling
            except Exception:
                pass
            time.sleep(2)

    def _channel_feishu_setup(self, channel_id: str, npm_spec: str, app_id: str, app_secret: str) -> dict:
        """Install plugin and save App ID + App Secret for Feishu."""
        if npm_spec and not self._check_plugin_installed(npm_spec):
            self._install_plugin(npm_spec)
            for _ in range(30):
                time.sleep(2)
                if self._check_plugin_installed(npm_spec):
                    break
            if not self._check_plugin_installed(npm_spec):
                return {"ok": False, "error": f"{channel_id} 插件安装失败"}

        try:
            p = ROOT / "data" / ".openclaw" / "openclaw.json"
            cfg = json.loads(p.read_text())
            if "channels" not in cfg:
                cfg["channels"] = {}
            if channel_id not in cfg["channels"]:
                cfg["channels"][channel_id] = {}
            cfg["channels"][channel_id]["dmPolicy"] = "open"
            cfg["channels"][channel_id]["groupPolicy"] = "open"
            cfg["channels"][channel_id]["allowFrom"] = ["*"]
            cfg["channels"][channel_id]["groupAllowFrom"] = ["*"]
            cfg["channels"][channel_id]["accounts"] = {
                "default": {"appId": app_id, "appSecret": app_secret, "enabled": True}
            }
            if "plugins" not in cfg:
                cfg["plugins"] = {"entries": {}}
            if "entries" not in cfg["plugins"]:
                cfg["plugins"]["entries"] = {}
            cfg["plugins"]["entries"][channel_id] = {"enabled": True}
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            return {"ok": True, "message": f"{channel_id} 已配置，重启 Gateway 后生效"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _channel_dingtalk_setup(self, channel_id: str, npm_spec: str, app_id: str, app_secret: str) -> dict:
        """Install plugin and save App ID + App Secret for DingTalk (clientId + clientSecret)."""
        if npm_spec and not self._check_plugin_installed(npm_spec):
            self._install_plugin(npm_spec)
            for _ in range(30):
                time.sleep(2)
                if self._check_plugin_installed(npm_spec):
                    break
            if not self._check_plugin_installed(npm_spec):
                return {"ok": False, "error": f"{channel_id} 插件安装失败"}

        try:
            p = ROOT / "data" / ".openclaw" / "openclaw.json"
            cfg = json.loads(p.read_text())
            if "channels" not in cfg:
                cfg["channels"] = {}
            if channel_id not in cfg["channels"]:
                cfg["channels"][channel_id] = {}
            cfg["channels"][channel_id]["dmPolicy"] = "open"
            cfg["channels"][channel_id]["groupPolicy"] = "open"
            cfg["channels"][channel_id]["allowFrom"] = ["*"]
            cfg["channels"][channel_id]["groupAllowFrom"] = ["*"]
            cfg["channels"][channel_id]["accounts"] = {
                "default": {"clientId": app_id, "clientSecret": app_secret, "enabled": True}
            }
            if "plugins" not in cfg:
                cfg["plugins"] = {"entries": {}}
            if "entries" not in cfg["plugins"]:
                cfg["plugins"]["entries"] = {}
            cfg["plugins"]["entries"][channel_id] = {"enabled": True}
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            return {"ok": True, "message": f"{channel_id} 已配置，重启 Gateway 后生效"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _channel_qqbot_setup(self, channel_id: str, npm_spec: str, app_id: str, app_secret: str) -> dict:
        """Install plugin and save App ID + Client Secret for QQ Bot."""
        if npm_spec and not self._check_plugin_installed(npm_spec):
            self._install_plugin(npm_spec)
            for _ in range(30):
                time.sleep(2)
                if self._check_plugin_installed(npm_spec):
                    break
            if not self._check_plugin_installed(npm_spec):
                return {"ok": False, "error": f"{channel_id} 插件安装失败"}

        try:
            p = ROOT / "data" / ".openclaw" / "openclaw.json"
            cfg = json.loads(p.read_text())
            if "channels" not in cfg:
                cfg["channels"] = {}
            if channel_id not in cfg["channels"]:
                cfg["channels"][channel_id] = {}
            cfg["channels"][channel_id]["dmPolicy"] = "open"
            cfg["channels"][channel_id]["groupPolicy"] = "open"
            cfg["channels"][channel_id]["allowFrom"] = ["*"]
            cfg["channels"][channel_id]["groupAllowFrom"] = ["*"]
            cfg["channels"][channel_id]["accounts"] = {
                "default": {"appId": app_id, "clientSecret": app_secret, "enabled": True}
            }
            if "plugins" not in cfg:
                cfg["plugins"] = {"entries": {}}
            if "entries" not in cfg["plugins"]:
                cfg["plugins"]["entries"] = {}
            cfg["plugins"]["entries"][channel_id] = {"enabled": True}
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            return {"ok": True, "message": f"{channel_id} 已配置，重启 Gateway 后生效"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _channel_token_setup(self, channel_id: str, npm_spec: str, token: str) -> dict:
        """Install plugin and save a bot token for token-based channels (generic fallback)."""
        # Step 1: Ensure plugin is installed
        if npm_spec and not self._check_plugin_installed(npm_spec):
            self._install_plugin(npm_spec)
            for _ in range(30):
                time.sleep(2)
                if self._check_plugin_installed(npm_spec):
                    break
            if not self._check_plugin_installed(npm_spec):
                return {"ok": False, "error": f"{channel_id} 插件安装失败"}

        # Step 2: Save token to config
        try:
            self._save_channel_credential(channel_id, "default", token)
            # Also enable plugin entry
            p = ROOT / "data" / ".openclaw" / "openclaw.json"
            cfg = json.loads(p.read_text())
            if "plugins" not in cfg:
                cfg["plugins"] = {"entries": {}}
            if "entries" not in cfg["plugins"]:
                cfg["plugins"]["entries"] = {}
            cfg["plugins"]["entries"][channel_id] = {"enabled": True}
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            return {"ok": True, "message": f"{channel_id} 已配置，重启 Gateway 后生效"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _save_channel_credential(self, channel_id: str, account_id: str, bot_token: str) -> None:
        """Write channel credentials into config so Gateway picks them up."""
        try:
            p = ROOT / "data" / ".openclaw" / "openclaw.json"
            cfg = json.loads(p.read_text())
            if "channels" not in cfg:
                cfg["channels"] = {}
            if channel_id not in cfg["channels"]:
                cfg["channels"][channel_id] = {}
            cfg["channels"][channel_id]["accounts"] = {
                account_id: {"token": bot_token, "enabled": True}
            }
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            print(f"[INFO] Saved {channel_id} credential for {account_id}", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] Failed to save {channel_id} credential: {e}", file=sys.stderr)

    def _save_weixin_credential(self, channel_id: str, account_id: str, bot_token: str) -> None:
        """Write WeChat credentials to the plugin's own credential file AND enable in config.

        The @tencent-weixin/openclaw-weixin plugin reads credentials from:
            <state-dir>/openclaw-weixin/accounts/<accountId>.json
        It uses "default" as the account ID when none is explicitly specified.
        We always save as "default" so the Gateway picks it up on its own
        credential-initiated login cycle.
        """
        state_dir = ROOT / "data" / ".openclaw" / ".openclaw" / "openclaw-weixin"
        accounts_dir = state_dir / "accounts"
        try:
            accounts_dir.mkdir(parents=True, exist_ok=True)
            # Always use "default" as the account file name — the Gateway auto-discovers
            # accounts by scanning this directory, and "default" matches the default
            # channel account key.
            cred_file = accounts_dir / "default.json"
            import datetime
            cred = {
                "token": bot_token,
                "userId": account_id,
                "savedAt": datetime.datetime.now().isoformat(),
            }
            cred_file.write_text(json.dumps(cred, indent=2, ensure_ascii=False))
            print(f"[INFO] Saved {channel_id} credential to {cred_file}", file=sys.stderr)
            # Also update accounts.json index — the weixin plugin uses this to
            # discover registered accounts. Without this, the channel won't start.
            index_file = accounts_dir.parent / "accounts.json"
            try:
                existing_ids = json.loads(index_file.read_text()) if index_file.exists() else []
            except (json.JSONDecodeError, FileNotFoundError):
                existing_ids = []
            if "default" not in existing_ids:
                existing_ids.append("default")
                index_file.write_text(json.dumps(existing_ids, indent=2))
                print(f"[INFO] Updated {channel_id} accounts index: {existing_ids}", file=sys.stderr)
            # Clean up any old per-user-id credential file from previous bindings
            old_file = accounts_dir / f"{account_id}.json"
            if old_file.exists() and old_file != cred_file:
                try:
                    old_file.unlink()
                    print(f"[INFO] Removed old credential file: {old_file}", file=sys.stderr)
                except Exception:
                    pass
        except Exception as e:
            print(f"[ERROR] Failed to save {channel_id} credential file: {e}", file=sys.stderr)
            # Fall back to config-based save
            self._save_channel_credential(channel_id, account_id, bot_token)
            return

        # Enable the plugin entry AND set channels config so Gateway picks it up on reload
        try:
            p = ROOT / "data" / ".openclaw" / "openclaw.json"
            cfg = json.loads(p.read_text())
            if "plugins" not in cfg:
                cfg["plugins"] = {"entries": {}}
            if "entries" not in cfg["plugins"]:
                cfg["plugins"]["entries"] = {}
            cfg["plugins"]["entries"][channel_id] = {"enabled": True}
            # Also write channel config so Gateway auto-starts the channel on next reload
            if "channels" not in cfg:
                cfg["channels"] = {}
            if channel_id not in cfg["channels"]:
                cfg["channels"][channel_id] = {}
            cfg["channels"][channel_id]["enabled"] = True
            cfg["channels"][channel_id]["dmPolicy"] = "open"
            cfg["channels"][channel_id]["groupPolicy"] = "open"
            cfg["channels"][channel_id]["allowFrom"] = ["*"]
            cfg["channels"][channel_id]["groupAllowFrom"] = ["*"]
            cfg["channels"][channel_id]["accounts"] = {
                "default": {"enabled": True}
            }
            p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            print(f"[INFO] Enabled {channel_id} plugin + channel in config", file=sys.stderr)

            # Also create pairing allowFrom file so all WeChat users can send messages.
            # The weixin plugin uses hardcoded dmPolicy="pairing" and reads authorized
            # sender IDs from credentials/openclaw-weixin-{accountId}-allowFrom.json.
            # Using allowFrom=["*"] authorizes ALL WeChat users automatically.
            allow_file = ROOT / "data" / ".openclaw" / ".openclaw" / "credentials" / f"openclaw-weixin-default-allowFrom.json"
            try:
                allow_file.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            allow_data = {"version": 1, "allowFrom": ["*"]}
            allow_file.write_text(json.dumps(allow_data, indent=2, ensure_ascii=False))
            print(f"[INFO] Created weixin allowFrom with wildcard", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] Failed to enable {channel_id} plugin: {e}", file=sys.stderr)

    def _unbind_channel(self, channel_id: str) -> dict:
        """Remove a channel's credentials and disable its plugin entry."""
        changes = []

        # 1. Remove credential file + accounts index (WeChat uses file-based storage)
        if channel_id == "openclaw-weixin":
                cred_file = ROOT / "data" / ".openclaw" / ".openclaw" / "openclaw-weixin" / "accounts" / "default.json"
                index_file = ROOT / "data" / ".openclaw" / ".openclaw" / "openclaw-weixin" / "accounts.json"
                try:
                    if cred_file.exists():
                        cred_file.unlink()
                        changes.append("已删除微信凭证文件")
                    if index_file.exists():
                        index_file.unlink()
                        changes.append("已清除账号索引")
                except Exception as e:
                    print(f"[WARN] Failed to delete credential file: {e}", file=sys.stderr)

        # 2. Remove channel accounts from config
        try:
            p = ROOT / "data" / ".openclaw" / "openclaw.json"
            cfg = json.loads(p.read_text())
            changed = False
            if "channels" in cfg and channel_id in cfg["channels"]:
                del cfg["channels"][channel_id]
                changed = True
                changes.append(f"已清除 {channel_id} 配置")
            if "plugins" in cfg and "entries" in cfg["plugins"] and channel_id in cfg["plugins"]["entries"]:
                cfg["plugins"]["entries"][channel_id] = {"enabled": False}
                changed = True
                changes.append(f"已禁用 {channel_id} 插件")
            if changed:
                p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        except Exception as e:
            return {"ok": False, "error": str(e)}

        return {"ok": True, "message": "; ".join(changes) if changes else "无需解绑"}

    def _check_plugin_installed(self, plugin_id: str) -> bool:
        """Check if a plugin package directory exists on disk."""
        safe_name = plugin_id.lstrip("@").replace("/", "-")
        plugins_dir = DATA_HOME / ".openclaw" / "npm" / "projects"
        if not plugins_dir.exists():
            return False
        return bool(sorted(plugins_dir.glob(f"{safe_name}*")))

    def _get_weixin_login_status(self, qrcode: str) -> dict:
        """Poll the ilink API for the current QR code login status."""
        try:
            url = f"https://ilinkai.weixin.qq.com/ilink/bot/get_qrcode_status?qrcode={qrcode}"
            req = urllib.request.Request(url, method="GET",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            status = data.get("status", "")
            if status == "confirmed":
                bot_token = data.get("bot_token")
                ilink_bot_id = data.get("ilink_bot_id")
                if bot_token and ilink_bot_id:
                    self._save_weixin_credential("openclaw-weixin", ilink_bot_id, bot_token)
                    # Auto-restart Gateway so the channel picks up the new credential immediately
                    try:
                        self._restart_gateway()
                    except Exception:
                        pass
                return {"ok": True, "status": "confirmed", "message": "扫码成功，已保存凭证并重启网关"}
            elif status == "expired":
                return {"ok": True, "status": "expired", "message": "二维码已过期，请刷新重试"}
            elif status == "scaned":
                return {"ok": True, "status": "scaned", "message": "已扫码，请在手机上确认授权"}
            elif status == "scaned_but_redirect":
                return {"ok": True, "status": "scaned", "message": "已扫码，请在新页面中确认授权"}
            elif status == "need_verifycode":
                return {"ok": True, "status": "need_verifycode", "message": "需要输入验证码"}
            else:
                return {"ok": True, "status": "wait", "message": "等待扫码..."}
        except Exception as e:
            return {"ok": False, "status": "error", "message": str(e)}

    def _get_weixin_qr(self) -> dict:
        """Fetch a WeChat login QR code from the ilink API."""
        try:
            url = "https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode?bot_type=3"
            req = urllib.request.Request(url, data=b"{}",
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                qr_url = data.get("qrcode_img_content", "")
                if qr_url:
                    return {"ok": True, "status": "qr_ready", "qrUrl": qr_url,
                            "qrcode": data.get("qrcode", ""),
                            "message": "请用微信扫描二维码"}
                return {"ok": False, "error": f"未获取到二维码: {json.dumps(data)[:200]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _plugin_status(self, plugin_id: str) -> dict:
        """Check the install status of a plugin."""
        proc = _plugin_processes.get(plugin_id)
        if proc is not None:
            rc = proc.poll()
            if rc is None:
                return {"ok": True, "status": "installing", "message": f"{plugin_id}..."}
            if rc == 0:
                out = proc.stdout.read() if proc.stdout else ""
                return {"ok": True, "status": "done", "message": f"{plugin_id} OK", "output": out[-2000:]}
            else:
                err = proc.stderr.read() if proc.stderr else ""
                return {"ok": False, "status": "failed",
                        "message": f"{plugin_id} fail (exit {rc})", "error": err[-2000:]}

        # No active process — check disk for installed plugins
        plugins_dir = DATA_HOME / ".openclaw" / "npm" / "projects"
        if not plugins_dir.exists():
            return {"ok": True, "status": "unknown", "message": "无插件目录"}

        # Match by npm package name → directory prefix
        safe_name = plugin_id.lstrip("@").replace("/", "-")
        matches = sorted(plugins_dir.glob(f"{safe_name}*"))
        if matches:
            return {"ok": True, "status": "done", "message": f"{plugin_id} 已安装"}
        return {"ok": True, "status": "unknown", "message": f"{plugin_id} 未安装"}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=3131)
    p.add_argument("--bind", type=str, default=DEFAULT_BIND,
                   help=f"Bind address (default: {DEFAULT_BIND}, use 0.0.0.0 for network access)")
    a = p.parse_args()
    print(f"🦞 OpenClaw Web UI → http://{a.bind}:{a.port}")
    print(f"   Starter:  http://{a.bind}:{a.port}/starter")
    print(f"   ControlUI: http://{a.bind}:{a.port}/  (auto-config injected)")
    print(f"   Gateway token: {AUTO_TOKEN}")
    HTTPServer((a.bind, a.port), Handler).serve_forever()
