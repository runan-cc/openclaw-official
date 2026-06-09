"""pytest fixtures for OpenClaw tests."""

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir() -> Path:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mock_config_file(temp_dir: Path) -> Path:
    """Create a mock openclaw.json config file."""
    config = {
        "agents": {"defaults": {"model": {"primary": "deepseek-chat"}}},
        "gateway": {"mode": "local", "auth": {"mode": "token", "token": "test-token-123"}},
        "models": {
            "mode": "merge",
            "providers": {
                "deepseek": {
                    "api": "openai-completions",
                    "apiKey": "sk-test-key",
                    "baseUrl": "https://api.deepseek.com/v1",
                    "models": [{"id": "deepseek-chat", "input": ["text"], "maxTokens": 8192, "name": "deepseek-chat", "reasoning": False}],
                }
            },
        },
    }
    config_path = temp_dir / "openclaw.json"
    config_path.write_text(json.dumps(config, indent=2))
    return config_path


@pytest.fixture
def mock_engine_dir(temp_dir: Path) -> Path:
    """Create a mock engine directory with package.json."""
    engine_dir = temp_dir / "engine"
    engine_dir.mkdir()
    pkg = {"name": "openclaw", "version": "2026.6.1", "description": "AI Gateway"}
    (engine_dir / "package.json").write_text(json.dumps(pkg))
    return engine_dir
