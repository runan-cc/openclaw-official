#!/usr/bin/env python3
"""
OpenClaw (开物) — Cross-platform GUI Launcher
Falls back to browser mode when tkinter is unavailable.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE_MODULE = ROOT / "app" / "core" / "node_modules" / "openclaw" / "openclaw.mjs"
ENGINE_DIR = ROOT / "app" / "core" / "node_modules" / "openclaw"
CONFIG_DIR = ROOT / "data" / ".openclaw"
CONFIG_FILE = CONFIG_DIR / "openclaw.json"
WORKSPACE_DIR = CONFIG_DIR / "workspace"
WEBUI_SERVER = ROOT / "webui" / "server.py"
WEBUI_PORT = 3131

sys.path.insert(0, str(ROOT))
from lib.common import get_node_binary, get_engine_version, load_config, is_port_open

HAS_TKINTER = False
try:
    import tkinter as tk
    from tkinter import scrolledtext
    HAS_TKINTER = True
except ImportError:
    pass


def get_node() -> str:
    return get_node_binary(ROOT)


def get_engine_ver() -> str:
    return get_engine_version(ENGINE_DIR)


def get_status() -> dict:
    info: dict = {"node": "?", "engine": False, "api_key": False, "ws_files": [], "skills": 0}
    try:
        r = subprocess.run([get_node(), "--version"], capture_output=True, text=True, timeout=3)
        info["node"] = r.stdout.strip() if r.returncode == 0 else "?"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    info["engine"] = ENGINE_MODULE.exists()
    info["skills"] = len(list(ENGINE_DIR.glob("skills/*"))) if ENGINE_DIR.exists() else 0
    if WORKSPACE_DIR.exists():
        info["ws_files"] = sorted(f.name for f in WORKSPACE_DIR.glob("*.md"))
    try:
        c = json.loads(CONFIG_FILE.read_text())
        providers = c.get("models", {}).get("providers", {})
        info["api_key"] = any(
            p.get("apiKey", "") and not p.get("apiKey", "").startswith("YOUR")
            for p in providers.values()
        )
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return info


# ══════════════════════════════════════════════
# TKINTER GUI — Cross-platform dark theme
# ══════════════════════════════════════════════
if HAS_TKINTER:

    class Cl:
        BG = "#0b0b0d"
        BG2 = "#111113"
        CARD = "#161618"
        CARD_HOVER = "#1c1c1f"
        BORDER = "#232326"
        ACCENT = "#e63f52"
        ACCENT_HOVER = "#f87171"
        TEXT = "#ededef"
        TEXT2 = "#a1a1aa"
        TEXT3 = "#6b6b75"
        GREEN = "#22c55e"
        YELLOW = "#f59e0b"
        RED = "#ef4444"
        CODE_BG = "#18181b"

    class App:
        def __init__(self) -> None:
            self.root = tk.Tk()
            self.root.title(f"OpenClaw {get_engine_ver()}")
            self.root.geometry("800x580")
            self.root.minsize(700, 480)
            self.root.configure(bg=Cl.BG)
            try:
                self.root.tk.call("tk::unsupported::MacWindowStyle", "useDarkTheme")
            except tk.TclError:
                pass

            self._build()
            self.root.after(500, self._refresh)
            self.root.protocol("WM_DELETE_WINDOW", self._close)

        def _build(self) -> None:
            self.root.columnconfigure(0, weight=0)
            self.root.columnconfigure(1, weight=1)
            self.root.rowconfigure(0, weight=1)

            self._sidebar()

            m = tk.Frame(self.root, bg=Cl.BG)
            m.grid(row=0, column=1, sticky="nsew")
            m.columnconfigure(0, weight=1)
            m.rowconfigure(0, weight=0)
            m.rowconfigure(1, weight=0)
            m.rowconfigure(2, weight=1)
            m.rowconfigure(3, weight=0)

            hf = tk.Frame(m, bg=Cl.BG)
            hf.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 4))
            tk.Label(hf, text="\U0001f99e  OpenClaw", font=("Inter", 22, "bold"),
                     bg=Cl.BG, fg=Cl.TEXT).pack(side=tk.LEFT)
            self.ver_lbl = tk.Label(hf, text=f"v{get_engine_ver()} · 全平台版",
                                     font=("Inter", 11), bg=Cl.BG, fg=Cl.TEXT3)
            self.ver_lbl.pack(side=tk.LEFT, padx=(10, 0))

            cf = tk.Frame(m, bg=Cl.BG)
            cf.grid(row=1, column=0, sticky="ew", padx=24, pady=(8, 4))

            actions = [
                ("\U0001f310  Web UI", "浏览器管理界面", self._webui, "#6366f1"),
                ("⚡  Gateway", "启动 AI 网关服务", self._gateway, "#22c55e"),
                ("\U0001f4ac  TUI 终端", "终端聊天界面", self._tui, "#f59e0b"),
                ("\U0001f4ca  Dashboard", "Web 控制面板", self._dashboard, "#a855f7"),
            ]
            for i, (title, desc, cmd, color) in enumerate(actions):
                self._action_card(cf, i, title, desc, cmd, color)

            sf = tk.Frame(m, bg=Cl.CARD, highlightbackground=Cl.BORDER, highlightthickness=1)
            sf.grid(row=2, column=0, sticky="ew", padx=24, pady=(4, 0))
            self.stat_labels = {}
            items = [("node", "Node.js"), ("engine", "引擎"), ("apikey", "API Key"), ("skills", "技能")]
            for i, (k, t) in enumerate(items):
                dot = tk.Label(sf, text="○", font=("Inter", 8, "bold"),
                               bg=Cl.CARD, fg=Cl.TEXT3)
                dot.grid(row=0, column=i * 2, padx=(16 if i > 0 else 16, 2), pady=10)
                txt = tk.Label(sf, text=f"{t}: ...", font=("Inter", 11),
                               bg=Cl.CARD, fg=Cl.TEXT2)
                txt.grid(row=0, column=i * 2 + 1, sticky="w", padx=(0, 0), pady=10)
                self.stat_labels[k + "_dot"] = dot
                self.stat_labels[k + "_txt"] = txt
                sf.columnconfigure(i * 2 + 1, weight=1)

            lf = tk.Frame(m, bg=Cl.BG)
            lf.grid(row=3, column=0, sticky="nsew", padx=24, pady=(8, 12))
            lf.columnconfigure(0, weight=1)
            lf.rowconfigure(1, weight=1)

            lh = tk.Frame(lf, bg=Cl.BG)
            lh.grid(row=0, column=0, sticky="ew")
            tk.Label(lh, text="\U0001f4cb  输出日志", font=("Inter", 10, "bold"),
                     bg=Cl.BG, fg=Cl.TEXT3).pack(side=tk.LEFT)
            tk.Button(lh, text="清空", font=("Inter", 9), bg=Cl.CARD, fg=Cl.TEXT3,
                      bd=0, padx=10, pady=2, cursor="hand2", activebackground=Cl.CARD_HOVER,
                      activeforeground=Cl.TEXT, command=self._clear_log).pack(side=tk.RIGHT)

            self.log = scrolledtext.ScrolledText(
                lf, font=("JetBrains Mono", 10), bg=Cl.CODE_BG, fg=Cl.TEXT2,
                insertbackground=Cl.ACCENT, bd=0, padx=10, pady=6, height=6,
                wrap=tk.WORD, highlightbackground=Cl.BORDER, highlightthickness=0)
            self.log.grid(row=1, column=0, sticky="nsew")
            self.log.tag_config("ok", foreground=Cl.GREEN)
            self.log.tag_config("warn", foreground=Cl.YELLOW)
            self.log.tag_config("err", foreground=Cl.RED)
            self._log(f"\U0001f99e OpenClaw v{get_engine_ver()} · 全平台版")
            self._log(f"\U0001f4c1 {ROOT}")

        def _sidebar(self) -> None:
            s = tk.Frame(self.root, bg=Cl.BG2, highlightbackground=Cl.BORDER, highlightthickness=1)
            s.grid(row=0, column=0, sticky="ns")

            tk.Label(s, text="\U0001f99e", font=("Inter", 24), bg=Cl.BG2, fg=Cl.ACCENT).pack(pady=(20, 4))
            tk.Label(s, text="开物", font=("Inter", 14, "bold"), bg=Cl.BG2, fg=Cl.TEXT).pack()
            tk.Label(s, text="OpenClaw", font=("Inter", 8), bg=Cl.BG2, fg=Cl.TEXT3).pack(pady=(0, 16))

            for icon, label, cmd in [
                ("\U0001f3e0", "首页", None),
                ("⚙️", "管理", None),
                ("\U0001f4d6", "文档", "https://docs.openclaw.ai"),
                ("\U0001f4ac", "Discord", "https://discord.gg/openclaw"),
                ("\U0001f4e6", "GitHub", "https://github.com/openclaw/openclaw"),
            ]:
                f = tk.Frame(s, bg=Cl.BG2, cursor="hand2")
                f.pack(fill="x", padx=8, pady=1)
                if cmd:
                    f.bind("<Button-1>", lambda e, u=cmd: webbrowser.open(u))
                tk.Label(f, text=f"{icon}  {label}", font=("Inter", 11), bg=Cl.BG2,
                         fg=Cl.TEXT3).pack(anchor="w", padx=12, pady=5)
                f.bind("<Enter>", lambda e, f=f: f.configure(bg=Cl.CARD_HOVER))
                f.bind("<Leave>", lambda e, f=f: f.configure(bg=Cl.BG2))

            tk.Label(s, text="", bg=Cl.BG2).pack(expand=True)
            self.conn_lbl = tk.Label(s, text="●  已就绪", font=("Inter", 9),
                                      bg=Cl.BG2, fg=Cl.TEXT3)
            self.conn_lbl.pack(pady=12)

        def _action_card(self, parent: tk.Frame, index: int, title: str, desc: str, command, color: str) -> None:
            row, col = divmod(index, 2)
            if col == 0:
                parent.columnconfigure(0, weight=1, uniform="ac")
                parent.columnconfigure(1, weight=1, uniform="ac")
                parent.rowconfigure(row, weight=0)

            f = tk.Frame(parent, bg=Cl.CARD, highlightbackground=Cl.BORDER,
                         highlightthickness=1, cursor="hand2", padx=14, pady=12)
            f.grid(row=row, column=col, sticky="ew", padx=4, pady=4)

            bar = tk.Frame(f, bg=color, height=3)
            bar.pack(fill="x", pady=(0, 8))

            title_lbl = tk.Label(f, text=title, font=("Inter", 13, "bold"),
                                  bg=Cl.CARD, fg=Cl.TEXT, cursor="hand2")
            title_lbl.pack(anchor="w")

            desc_lbl = tk.Label(f, text=desc, font=("Inter", 10),
                                bg=Cl.CARD, fg=Cl.TEXT3, cursor="hand2")
            desc_lbl.pack(anchor="w", pady=(2, 0))

            for w in [f, title_lbl, desc_lbl, bar]:
                w.bind("<Button-1>", lambda e, c=command: c())
                w.bind("<Enter>", lambda e, f=f, bar=bar, color=color: self._card_hover(f, bar, color))
                w.bind("<Leave>", lambda e, f=f, bar=bar: self._card_leave(f, bar))

            badge = tk.Label(f, text="", font=("Inter", 8), bg=Cl.CARD, fg=Cl.TEXT3)
            badge.pack(anchor="e")

        def _card_hover(self, f, bar, color):
            f.configure(bg=Cl.CARD_HOVER)

        def _card_leave(self, f, bar):
            f.configure(bg=Cl.CARD)

        def _log(self, msg: str, tag: str = "") -> None:
            ts = time.strftime("%H:%M:%S")

            def a() -> None:
                self.log.insert(tk.END, f"  {ts}  ", "")
                self.log.insert(tk.END, f"{msg}\n", tag)
                self.log.see(tk.END)
            self.root.after(0, a)

        def _clear_log(self) -> None:
            self.log.delete("1.0", tk.END)

        def _set_stat(self, key: str, status: str, text: str) -> None:
            colors = {"ok": Cl.GREEN, "warn": Cl.YELLOW, "err": Cl.RED}
            dots = {"ok": "●", "warn": "◑", "err": "○"}
            if key + "_dot" in self.stat_labels:
                self.stat_labels[key + "_dot"].configure(text=dots.get(status, "○"),
                                                          fg=colors.get(status, Cl.TEXT3))
                self.stat_labels[key + "_txt"].configure(text=text)

        def _refresh(self) -> None:
            def t() -> None:
                st = get_status()
                self.root.after(0, lambda: self._set_stat("node", "ok" if st["node"] != "?" else "err",
                                                           f"Node.js  {st['node']}"))
                self.root.after(0, lambda: self._set_stat("engine", "ok" if st["engine"] else "err",
                                                           f"引擎  v{get_engine_ver()}"))
                self.root.after(0, lambda: self._set_stat("apikey", "ok" if st["api_key"] else "warn",
                                                           f"API Key  {'已配置' if st['api_key'] else '未配置'}"))
                self.root.after(0, lambda: self._set_stat("skills", "ok",
                                                           f"技能  {st['skills']} 个内置"))
                self.root.after(10000, self._refresh)
            threading.Thread(target=t, daemon=True).start()

        def _run_cli(self, cmd: list, desc: str) -> None:
            def t() -> None:
                self._log(f"▶ {desc}...")
                try:
                    r = subprocess.run(
                        [get_node(), str(ENGINE_MODULE)] + cmd,
                        capture_output=True, text=True, timeout=30,
                        env={"OPENCLAW_HOME": str(CONFIG_DIR), **os.environ})
                    out = (r.stdout or "")[:600]
                    err = (r.stderr or "")[:200]
                    if out:
                        for line in out.strip().split("\n")[:12]:
                            self._log(f"  {line}")
                    if err:
                        self._log(f"  ⚠ {err.strip()[:200]}", "warn")
                    self._log(
                        f"✓ {desc}" if r.returncode == 0 else f"✗ {desc} (code {r.returncode})",
                        "ok" if r.returncode == 0 else "warn")
                except subprocess.TimeoutExpired:
                    self._log(f"⏱ {desc} 超时", "warn")
                except (FileNotFoundError, OSError) as e:
                    self._log(f"✗ {e}", "err")
            threading.Thread(target=t, daemon=True).start()

        def _find_terminal(self) -> tuple:
            """Probe for a terminal emulator. Cross-platform."""
            import platform
            system = platform.system()

            # Windows
            if system == "Windows":
                return "cmd.exe", ["cmd", "/c", "start", "cmd", "/K"]

            # macOS
            if system == "Darwin":
                return "Terminal.app", ["open", "-a", "Terminal"]

            # Linux
            for name, args in [
                ("ptyxis", ["ptyxis", "--"]),
                ("x-terminal-emulator", ["x-terminal-emulator", "-x"]),
                ("gnome-terminal", ["gnome-terminal", "--"]),
                ("xfce4-terminal", ["xfce4-terminal", "-x"]),
                ("lxterminal", ["lxterminal", "-e"]),
                ("konsole", ["konsole", "-e"]),
                ("tilix", ["tilix", "-e"]),
                ("terminator", ["terminator", "-e"]),
                ("xterm", ["xterm", "-e"]),
                ("urxvt", ["urxvt", "-e"]),
            ]:
                if shutil.which(name):
                    return name, args
            return None, None

        def _run_term(self, cmd: list, desc: str) -> None:
            import platform
            name, tmpl = self._find_terminal()
            if not name:
                self._log(f"⚠ 未找到终端，请手动运行:", "warn")
                self._log(f"   cd {ROOT} && ./openclaw {' '.join(cmd)}", "warn")
                return
            self._log(f"▶ 在 {name} 中启动: {desc}")

            system = platform.system()
            if system == "Windows":
                shell_cmd = f"cd /d {ROOT} && echo *** OpenClaw *** && openclaw {' '.join(cmd)}"
                try:
                    subprocess.Popen(tmpl + [shell_cmd])
                except (FileNotFoundError, OSError) as e:
                    self._log(f"⚠ 启动终端失败: {e}", "err")
                return

            if system == "Darwin":
                shell_cmd = f'cd "{ROOT}" && echo "~~~ OpenClaw ~~~" && ./openclaw {" ".join(cmd)}; echo; echo "--- Press Return to close ---"; read'
                try:
                    subprocess.Popen(["osascript", "-e",
                                      f'tell app "Terminal" to do script "{shell_cmd}"'])
                except (FileNotFoundError, OSError):
                    try:
                        subprocess.Popen(["open", "-a", "Terminal", str(ROOT)])
                    except (FileNotFoundError, OSError) as e:
                        self._log(f"⚠ 启动终端失败: {e}", "err")
                return

            # Linux
            shell_cmd = f"cd {ROOT} && ./openclaw {' '.join(cmd)}; echo; echo '--- Press Enter to close ---'; read"
            try:
                subprocess.Popen(tmpl + ["bash", "-c", shell_cmd])
            except (FileNotFoundError, OSError) as e:
                self._log(f"⚠ 启动终端失败: {e}", "err")
                self._log(f"   手动: cd {ROOT} && ./openclaw {' '.join(cmd)}")

        def _webui(self) -> None:
            def t() -> None:
                already_running = is_port_open("127.0.0.1", WEBUI_PORT)
                if already_running:
                    self._log(f"\U0001f310 Web UI 已在运行 → http://localhost:{WEBUI_PORT}", "ok")
                    webbrowser.open(f"http://localhost:{WEBUI_PORT}")
                    return

                self._log("\U0001f310 启动 Web UI...")
                log_file = ROOT / "data" / ".openclaw" / "logs" / "webui.log"
                log_file.parent.mkdir(parents=True, exist_ok=True)
                max_retries = 3
                for attempt in range(max_retries):
                    with open(str(log_file), "a") as lf:
                        p = subprocess.Popen(
                            [sys.executable, str(WEBUI_SERVER), "--port", str(WEBUI_PORT)],
                            stdout=subprocess.DEVNULL,
                            stderr=lf,
                            cwd=str(WEBUI_SERVER.parent))
                    time.sleep(2)
                    if p.poll() is None:
                        webbrowser.open(f"http://localhost:{WEBUI_PORT}")
                        self._log(f"✅ Web UI → http://localhost:{WEBUI_PORT}", "ok")
                        return
                    self._log(f"⚠ Web UI 启动失败 (尝试 {attempt + 1}/{max_retries})", "warn")
                self._log("❌ Web UI 启动失败，请检查端口 3131 是否被占用", "err")
            threading.Thread(target=t, daemon=True).start()

        def _gateway(self) -> None:
            running = is_port_open("127.0.0.1", 18789)
            if running:
                self._log("✅ Gateway 正在运行 (端口 18789)", "ok")
                webbrowser.open("http://127.0.0.1:18789/")
            else:
                self._log("⚠️ Gateway 未运行，请启动: ./openclaw gateway run", "warn")

        def _tui(self) -> None:
            self._run_term(["tui"], "TUI 终端")

        def _dashboard(self) -> None:
            self._log("\U0001f680 打开 Dashboard...", "ok")
            webbrowser.open("http://127.0.0.1:18789/")

        def _close(self) -> None:
            self.root.destroy()

        def run(self) -> None:
            self.root.mainloop()


# ══════════════════════════════════════════════
# CLI fallback — browser-only mode
# ══════════════════════════════════════════════
def main() -> None:
    if not is_port_open("127.0.0.1", WEBUI_PORT):
        subprocess.Popen(
            [sys.executable, str(WEBUI_SERVER), "--port", str(WEBUI_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(WEBUI_SERVER.parent))
        time.sleep(2)
    webbrowser.open("http://localhost:3131/starter")
    print("\U0001f99e OpenClaw — 配置页面已打开")
    print(f"   {ROOT}/webui/starter.html")
    print(f"   http://localhost:3131/starter")


if __name__ == "__main__":
    if HAS_TKINTER:
        App().run()
    else:
        main()
