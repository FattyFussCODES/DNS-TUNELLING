"""Configuration loading rejects retired transport modes."""

import json

from app import config


def test_retired_mode_uses_safe_defaults_and_drops_unknown_options(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "mode": "retired-mode",
        "server": "old.invalid",
        "port": 49152,
        "retired_address": "old.invalid:49152",
        "delay": 0.2,
    }), encoding="utf-8")

    loaded = config.load_config(path)
    assert loaded["mode"] == config.DEFAULTS["mode"]
    assert loaded["server"] == config.DEFAULTS["server"]
    assert loaded["port"] == config.DEFAULTS["port"]
    assert loaded["delay"] == 0.2
    assert "retired_address" not in loaded

    config.save_config(loaded, path)
    assert "retired_address" not in json.loads(path.read_text(encoding="utf-8"))


def test_retired_mesh_mode_preserves_endpoint(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "mode": "Skein", "server": "192.0.2.11", "port": 15353,
    }), encoding="utf-8")
    loaded = config.load_config(path)
    assert loaded["mode"] == "Custom"
    assert loaded["server"] == "192.0.2.11"
    assert loaded["port"] == 15353
