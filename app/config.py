"""Presets, defaults, and config.json load/save."""

from __future__ import annotations

import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
DOMAIN = "dnstunnel.cc.cd"

DEFAULT_SERVER = "10.144.144.89"
DEFAULT_PORT = 53
DEFAULT_DELAY = 0.05

# Real addresses live here, as GUI presets, and nowhere else in the repo.
PRESETS = [
    {"label": "Skein - Aviral", "server": "10.144.144.89", "port": 53, "mode": "Skein"},
    {"label": "Skein - Yennefer", "server": "10.144.144.1", "port": 53, "mode": "Skein"},
    {"label": "Same Wi-Fi - Aviral", "server": "192.168.29.184", "port": 53, "mode": "Same Wi-Fi"},
    {"label": "Public Relay - Yennefer", "server": "115.97.155.115", "port": 53, "mode": "Public Relay"},
    {"label": "Loopback", "server": "127.0.0.1", "port": 5353, "mode": "Loopback"},
    {"label": "Custom", "server": "", "port": 53, "mode": "Custom"},
]

MODES = ["Skein", "Same Wi-Fi", "Public Relay", "Playit", "Domain"]
DOMAIN_MODE_SERVER = "8.8.8.8"
PLAYIT_DECODER_PORT = 5353

DEFAULTS = {
    "server": DEFAULT_SERVER,
    "port": DEFAULT_PORT,
    "delay": DEFAULT_DELAY,
    "received_dir": "received",
    "history_db": "history.db",
    "mode": "Skein",
    # Domain mode stays gated until the direct public relay test has passed.
    "domain_verified": False,
    "playit_address": "",
}

RECEIVED_DIR = APP_DIR / "received"


def load_config(path: str | Path = CONFIG_PATH) -> dict:
    """Defaults merged with what is on disk; a broken file never crashes."""
    config = dict(DEFAULTS)
    target = Path(path)
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return config
    if not isinstance(data, dict):
        return config
    for key, default in DEFAULTS.items():
        if key not in data:
            continue
        value = data[key]
        try:
            if isinstance(default, bool):
                config[key] = bool(value)
            elif isinstance(default, int):
                config[key] = int(value)
            elif isinstance(default, float):
                config[key] = float(value)
            else:
                config[key] = str(value)
        except (TypeError, ValueError):
            continue
    if config["mode"] not in MODES:
        config["mode"] = DEFAULTS["mode"]
    if not 1 <= config["port"] <= 65535:
        config["port"] = DEFAULTS["port"]
    if not 0.01 <= config["delay"] <= 1.0:
        config["delay"] = DEFAULTS["delay"]
    return config


def save_config(config: dict, path: str | Path = CONFIG_PATH) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: config.get(key, default) for key, default in DEFAULTS.items()}
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return target


def resolve_path(value: str | Path) -> Path:
    """Relative paths are relative to the app folder, not the shell's cwd."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (APP_DIR / path)


def received_dir(config: dict) -> Path:
    return resolve_path(config.get("received_dir", DEFAULTS["received_dir"]))


def history_path(config: dict) -> Path:
    return resolve_path(config.get("history_db", DEFAULTS["history_db"]))
