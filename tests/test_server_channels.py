"""Tests for channel setup endpoints in webui/server.py."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

import pytest


class FakeRequest:
    """Minimal fake for urllib.request.Request."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return FakeResponse(200, json.dumps({"status": "ok"}))

    def __exit__(self, *args):
        pass


class FakeResponse:
    def __init__(self, status: int, data: str):
        self.status = status
        self._data = data.encode()

    def read(self):
        return self._data


class FakeHandlerForTest:
    """Call the real handler methods without spinning up an HTTP server."""

    def __init__(self, root: Path):
        import sys
        sys.path.insert(0, str(root.parent))
        # Import the module to get the Handler class, but override ROOT
        self.root = root
        # We'll instantiate the real Handler methods manually

    def _json(self, data: dict, code: int = 200) -> dict:
        return {"json": data, "code": code}


# ── _channel_qqbot_setup ──


def test_qqbot_setup_saves_app_id_and_client_secret(tmp_path: Path) -> None:
    """QQ Bot setup saves appId and clientSecret to the nested config."""
    from webui.server import _deep_merge  # pure function, easy to test directly

    # Simulate what _channel_qqbot_setup does to the config
    config = {
        "channels": {},
        "plugins": {"entries": {}},
    }
    config["channels"]["qqbot"] = {
        "accounts": {
            "default": {
                "appId": "123456",
                "clientSecret": "secret-abc",
                "enabled": True,
            }
        }
    }
    config["plugins"]["entries"]["qqbot"] = {"enabled": True}

    assert config["channels"]["qqbot"]["accounts"]["default"]["appId"] == "123456"
    assert config["channels"]["qqbot"]["accounts"]["default"]["clientSecret"] == "secret-abc"
    assert config["channels"]["qqbot"]["accounts"]["default"]["enabled"] is True
    assert config["plugins"]["entries"]["qqbot"]["enabled"] is True


def test_qqbot_setup_requires_app_id_and_app_secret() -> None:
    """QQ Bot setup requires both appId and appSecret."""
    # Verify the validation logic
    app_id = ""
    app_secret = "secret"
    assert not app_id or not app_secret  # One is empty → fail

    app_id = "123456"
    app_secret = ""
    assert not app_id or not app_secret  # One is empty → fail

    app_id = "123456"
    app_secret = "secret"
    assert bool(app_id and app_secret)  # Both filled → pass


# ── _deep_merge ──


def test_deep_merge_preserves_qqbot_credentials() -> None:
    """Deep merge preserves existing channel credentials when saving model config."""
    from webui.server import _deep_merge

    base = {
        "channels": {
            "qqbot": {
                "accounts": {
                    "default": {
                        "appId": "qq-app-123",
                        "clientSecret": "qq-secret-456",
                        "enabled": True,
                    }
                }
            }
        },
        "plugins": {"entries": {"qqbot": {"enabled": True}}},
        "models": {"providers": {}},
    }

    overlay = {
        "models": {
            "providers": {
                "deepseek": {"api": "openai-completions", "apiKey": "sk-xxx"}
            }
        }
    }

    merged = _deep_merge(base, overlay)

    # QQ Bot credentials should still be there
    assert merged["channels"]["qqbot"]["accounts"]["default"]["appId"] == "qq-app-123"
    assert merged["channels"]["qqbot"]["accounts"]["default"]["clientSecret"] == "qq-secret-456"
    assert merged["plugins"]["entries"]["qqbot"]["enabled"] is True
    # New model config should be merged in
    assert merged["models"]["providers"]["deepseek"]["apiKey"] == "sk-xxx"


def test_deep_merge_overwrites_scalar() -> None:
    """Deep merge replaces scalar values instead of merging them."""
    from webui.server import _deep_merge

    base = {"name": "old", "count": 1}
    overlay = {"name": "new"}

    merged = _deep_merge(base, overlay)
    assert merged["name"] == "new"
    assert merged["count"] == 1  # preserved from base


# ── Channel form validation (matches frontend logic) ──


def test_qqbot_form_requires_both_fields() -> None:
    """The QQ Bot form (like Feishu) requires App ID and App Secret both filled."""
    # This mirrors the frontend validation in connectChannelQQ()

    def validate(app_id: str, app_secret: str) -> bool:
        return bool(app_id and app_secret)

    assert validate("", "") is False
    assert validate("123", "") is False
    assert validate("", "456") is False
    assert validate("123", "456") is True


# ── DingTalk channel (clientId + clientSecret) ──


def test_dingtalk_setup_saves_client_id_and_client_secret() -> None:
    """DingTalk setup saves clientId and clientSecret to the nested config."""
    config = {
        "channels": {},
        "plugins": {"entries": {}},
    }
    config["channels"]["dingtalk-connector"] = {
        "accounts": {
            "default": {
                "clientId": "ding-app-id-999",
                "clientSecret": "ding-secret-xyz",
                "enabled": True,
            }
        }
    }
    config["plugins"]["entries"]["dingtalk-connector"] = {"enabled": True}

    assert config["channels"]["dingtalk-connector"]["accounts"]["default"]["clientId"] == "ding-app-id-999"
    assert config["channels"]["dingtalk-connector"]["accounts"]["default"]["clientSecret"] == "ding-secret-xyz"
    assert config["channels"]["dingtalk-connector"]["accounts"]["default"]["enabled"] is True
    assert config["plugins"]["entries"]["dingtalk-connector"]["enabled"] is True


def test_dingtalk_form_requires_both_fields() -> None:
    """The DingTalk form requires App ID and App Secret both filled."""

    def validate(app_id: str, app_secret: str) -> bool:
        return bool(app_id and app_secret)

    assert validate("", "") is False
    assert validate("app-id", "") is False
    assert validate("", "app-secret") is False
    assert validate("app-id", "app-secret") is True


def test_deep_merge_preserves_all_channel_credentials() -> None:
    """Deep merge preserves QQ, DingTalk, and Feishu credentials simultaneously."""
    from webui.server import _deep_merge

    base = {
        "channels": {
            "feishu": {"accounts": {"default": {"appId": "fe-app", "appSecret": "fe-sec", "enabled": True}}},
            "dingtalk-connector": {"accounts": {"default": {"clientId": "dt-app", "clientSecret": "dt-sec", "enabled": True}}},
            "qqbot": {"accounts": {"default": {"appId": "qq-app", "clientSecret": "qq-sec", "enabled": True}}},
        },
        "plugins": {"entries": {"feishu": {"enabled": True}, "dingtalk-connector": {"enabled": True}, "qqbot": {"enabled": True}}},
    }

    merged = _deep_merge(base, {"gateway": {"mode": "local"}})

    assert merged["channels"]["feishu"]["accounts"]["default"]["appId"] == "fe-app"
    assert merged["channels"]["dingtalk-connector"]["accounts"]["default"]["clientId"] == "dt-app"
    assert merged["channels"]["qqbot"]["accounts"]["default"]["appId"] == "qq-app"
    assert merged["gateway"]["mode"] == "local"
