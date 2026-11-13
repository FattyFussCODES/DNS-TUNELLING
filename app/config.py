"""Presets and defaults. Config-file load/save arrives in Step 3."""

from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DOMAIN = "dnstunnel.cc.cd"

DEFAULT_SERVER = "10.144.144.89"
DEFAULT_PORT = 53
DEFAULT_DELAY = 0.05

PRESETS = [
    {"label": "Skein - Aviral", "server": "10.144.144.89", "port": 53, "mode": "Skein"},
    {"label": "Skein - Yennefer", "server": "10.144.144.1", "port": 53, "mode": "Skein"},
    {"label": "Same Wi-Fi - Aviral", "server": "192.168.29.184", "port": 53, "mode": "Same Wi-Fi"},
    {"label": "Public Relay - Yennefer", "server": "115.97.155.115", "port": 53, "mode": "Public Relay"},
    {"label": "Loopback", "server": "127.0.0.1", "port": 5353, "mode": "Loopback"},
    {"label": "Custom", "server": "", "port": 53, "mode": "Custom"},
]

RECEIVED_DIR = APP_DIR / "received"
