"""Tests for lib/common.py — shared utilities."""

import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from lib.common import (
    get_node_binary,
    get_engine_version,
    load_config,
    is_port_open,
    run_node_command,
)


# ── get_node_binary ──

def test_get_node_binary_bundled(tmp_path: Path) -> None:
    """Returns the bundled Node binary when system node is unavailable."""
    root = tmp_path
    bundled = root / "app" / "runtime" / "node-linux-x64" / "bin" / "node"
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    bundled.chmod(0o755)

    # Patch platform.system() to Linux and which() to simulate no system node
    with patch("shutil.which", return_value=None), patch("platform.system", return_value="Linux"), patch("platform.machine", return_value="x86_64"):
        result = get_node_binary(root)
    assert result == str(bundled)


def test_get_node_binary_fallback() -> None:
    """Falls back to 'node' when no system AND no bundled runtime exists."""
    with patch("shutil.which", return_value=None):
        result = get_node_binary(Path("/nonexistent-openclaw-root"))
    assert result == "node"


# ── get_engine_version ──

def test_get_engine_version_valid(mock_engine_dir: Path) -> None:
    """Reads the engine version from package.json."""
    result = get_engine_version(mock_engine_dir)
    assert result == "2026.6.1"


def test_get_engine_version_missing_file(tmp_path: Path) -> None:
    """Returns '?' when package.json does not exist."""
    result = get_engine_version(tmp_path)
    assert result == "?"


def test_get_engine_version_invalid_json(tmp_path: Path) -> None:
    """Returns '?' when package.json contains invalid JSON."""
    (tmp_path / "package.json").write_text("not json")
    result = get_engine_version(tmp_path)
    assert result == "?"


# ── load_config ──

def test_load_config_valid(mock_config_file: Path) -> None:
    """Loads and parses a valid config file."""
    result = load_config(mock_config_file)
    assert isinstance(result, dict)
    assert result["agents"]["defaults"]["model"]["primary"] == "deepseek-chat"
    assert result["models"]["providers"]["deepseek"]["apiKey"] == "sk-test-key"


def test_load_config_file_not_found(tmp_path: Path) -> None:
    """Returns empty dict when config file does not exist."""
    result = load_config(tmp_path / "nonexistent.json")
    assert result == {}


def test_load_config_invalid_json(tmp_path: Path) -> None:
    """Returns empty dict when config file contains invalid JSON."""
    p = tmp_path / "bad.json"
    p.write_text("{ invalid json }")
    result = load_config(p)
    assert result == {}


# ── is_port_open ──

def test_is_port_open_free_port() -> None:
    """Returns False for a port that is not open."""
    # Use a high port unlikely to be in use
    result = is_port_open("127.0.0.1", 59999, timeout=0.1)
    assert result is False


def test_is_port_open_invalid_host() -> None:
    """Returns False for an unreachable host."""
    result = is_port_open("192.0.2.1", 80, timeout=0.5)
    assert result is False


def test_is_port_open_socket_error() -> None:
    """Returns False when a low-level socket error occurs."""
    with patch("socket.socket") as mock_socket:
        mock_socket.return_value.connect_ex.side_effect = OSError("mocked socket error")
        result = is_port_open("127.0.0.1", 12345)
        assert result is False


# ── run_node_command ──

def test_run_node_command_with_env() -> None:
    """run_node_command passes extra_env to the subprocess."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        node = "node"
        mjs = Path("/fake/engine.mjs")
        result = run_node_command(
            node, mjs, ["--version"], timeout=10,
            extra_env={"OPENCLAW_TEST_ENV": "1"},
        )
        assert result.returncode == 0
        # Verify extra env was passed
        call_env = mock_run.call_args[1]["env"]
        assert call_env["OPENCLAW_TEST_ENV"] == "1"


def test_run_node_command_timeout(tmp_path: Path) -> None:
    """Handles command timeout gracefully."""
    node = "node"
    # Create a script that spins forever (blocking, not async)
    script = tmp_path / "spin.js"
    script.write_text("while (true) {}\n")

    with pytest.raises(subprocess.TimeoutExpired):
        run_node_command(node, script, [], timeout=1)
