"""OpenClaw shared utilities — Node.js resolution, config loading, port checks."""

import json
import shutil
import socket
import subprocess
from pathlib import Path


def get_node_binary(root: Path) -> str:
    """Resolve the Node.js binary path.

    Prefers system node (may be newer than bundled), falls back to bundled
    runtime, returns "node" as last resort.
    """
    # 1. System node — likely newer (e.g. nvm v22.22 vs bundled v22.14)
    system_node = shutil.which("node")
    if system_node:
        return system_node
    # 2. Bundled runtime
    candidates = [
        root / "app" / "runtime" / "node-linux-x64" / "bin" / "node",
        root / "app" / "runtime" / "node-linux-x64" / "node",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    # 3. Last resort
    return "node"


def get_engine_version(engine_dir: Path) -> str:
    """Read the OpenClaw engine version from its package.json.

    Returns the version string, or "?" on failure.
    """
    try:
        pkg = json.loads((engine_dir / "package.json").read_text())
        return pkg.get("version", "?")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "?"


def load_config(config_path: Path) -> dict:
    """Load the OpenClaw JSON configuration file.

    Returns a dict with the parsed config, or an empty dict on failure.
    """
    try:
        return json.loads(config_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check whether a TCP port is open on the given host."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port)) == 0
        return result
    except (OSError, socket.error):
        return False
    finally:
        sock.close()


def run_node_command(
    node: str,
    engine_mjs: Path,
    args: list[str],
    timeout: int = 30,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run an OpenClaw CLI command via Node.js.

    Returns the CompletedProcess with captured stdout/stderr.
    """
    env = dict(subprocess.os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [node, str(engine_mjs)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
