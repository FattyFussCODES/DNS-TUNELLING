"""Presets, defaults, and config.json load/save."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from platformdirs import user_data_path

LEGACY_APP_DIR = Path(__file__).resolve().parent.parent
APP_DIR = user_data_path("DNSMuggle", appauthor=False)
CONFIG_PATH = APP_DIR / "config.json"
DOMAIN = "dnstunnel.cc.cd"

DEFAULT_SERVER = "127.0.0.1"
DEFAULT_PORT = 5353
DEFAULT_DELAY = 0.01

# Loopback is universal; other addresses are entered by the user.
PRESETS = [
    {"label": "Loopback", "server": "127.0.0.1", "port": 5353, "mode": "Loopback"},
    {"label": "Custom", "server": "", "port": 53, "mode": "Custom"},
]

MODES = ["Custom", "Same Wi-Fi", "Public Relay", "Domain"]
DOMAIN_MODE_SERVER = "8.8.8.8"

DEFAULTS = {
    "server": DEFAULT_SERVER,
    "port": DEFAULT_PORT,
    "delay": DEFAULT_DELAY,
    "received_dir": "received",
    "history_db": "history.db",
    "mode": "Custom",
    # Domain mode stays gated until the direct public relay test has passed.
    "domain_verified": False,
}

RECEIVED_DIR = APP_DIR / "received"

# Consumed by the GUI after loading; never saved as part of the configuration.
MIGRATION_WARNINGS: list[str] = []


def _copy_legacy_file(source: Path, target: Path) -> None:
    """Publish a complete staged copy only if the destination does not exist."""
    if os.path.lexists(target):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".migration-", dir=target.parent)
    os.close(fd)
    staged = Path(temporary)
    try:
        shutil.copy2(source, staged)
        try:
            os.link(staged, target)
        except FileExistsError:
            pass
    finally:
        staged.unlink(missing_ok=True)


def _copy_legacy_path(source: Path, target: Path) -> None:
    if source.is_symlink():
        return
    try:
        source.stat()
    except FileNotFoundError:
        return
    if source.is_file():
        _copy_legacy_file(source, target)
    elif source.is_dir():
        def raise_walk_error(error: OSError) -> None:
            raise error

        for root, dirs, files in os.walk(source, onerror=raise_walk_error):
            root_path = Path(root)
            dirs[:] = [name for name in dirs if not (root_path / name).is_symlink()]
            for name in files:
                item = root_path / name
                if not item.is_symlink():
                    _copy_legacy_file(item, target / item.relative_to(source))


def _migrate_legacy_data() -> tuple[Path | None, dict[str, Path]]:
    """Copy legacy data without overwriting, retaining originals on failure."""
    MIGRATION_WARNINGS.clear()
    if LEGACY_APP_DIR == APP_DIR or (APP_DIR / ".lab-migration-v1").exists():
        return None, {}

    old_config = LEGACY_APP_DIR / "config.json"
    new_config = APP_DIR / "config.json"
    config_source = new_config if os.path.lexists(new_config) else old_config
    data = {}
    try:
        if os.path.lexists(config_source):
            with config_source.open(encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("configuration is not an object")
    except (OSError, UnicodeError, ValueError) as exc:
        MIGRATION_WARNINGS.append(f"Could not read migration configuration {config_source}: {exc}")
        return (old_config if config_source == old_config else None), {}

    fallback_config = None
    fallback_paths: dict[str, Path] = {}
    try:
        _copy_legacy_path(old_config, new_config)
    except OSError as exc:
        MIGRATION_WARNINGS.append(f"Could not migrate {old_config} to {new_config}: {exc}")
        if not os.path.lexists(new_config):
            fallback_config = old_config

    paths: list[tuple[Path, Path, str | None]] = []
    for key in ("history_db", "received_dir"):
        value = data.get(key, DEFAULTS[key])
        if not isinstance(value, str):
            continue
        relative = Path(value).expanduser()
        if not relative.is_absolute():
            paths.append((LEGACY_APP_DIR / relative, APP_DIR / relative, key))
    for name in ("history.db", "received", "reports"):
        source, target = LEGACY_APP_DIR / name, APP_DIR / name
        if not any(item[0] == source and item[1] == target for item in paths):
            paths.append((source, target, None))

    for source, target, key in paths:
        # A failed directory merge cannot represent all legacy files at the
        # destination. Keep using the original if there was no prior target.
        existed = os.path.lexists(target)
        try:
            if source.resolve() != target.resolve():
                _copy_legacy_path(source, target)
        except OSError as exc:
            MIGRATION_WARNINGS.append(f"Could not migrate {source} to {target}: {exc}")
            if key and not existed:
                fallback_paths[key] = source

    if not MIGRATION_WARNINGS:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            (APP_DIR / ".lab-migration-v1").touch()
        except OSError as exc:
            MIGRATION_WARNINGS.append(f"Could not save migration marker: {exc}")
    return fallback_config, fallback_paths


def load_config(path: str | Path = CONFIG_PATH) -> dict:
    """Defaults merged with what is on disk; a broken file never crashes."""
    config = dict(DEFAULTS)
    target = Path(path)
    fallback_config = None
    fallback_paths: dict[str, Path] = {}
    if target == CONFIG_PATH:
        fallback_config, fallback_paths = _migrate_legacy_data()
    for key, source in fallback_paths.items():
        config[key] = str(source)
    try:
        with open(fallback_config or target, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
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
    for key, source in fallback_paths.items():
        config[key] = str(source)
    if config["mode"] == "Skein":
        # Retired label; preserve the user's endpoint as a custom transport.
        config["mode"] = "Custom"
    if config["mode"] not in MODES:
        config["mode"] = DEFAULTS["mode"]
        config["server"] = DEFAULTS["server"]
        config["port"] = DEFAULTS["port"]
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
    """Resolve relative paths against the per-user application data folder."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (APP_DIR / path)


def received_dir(config: dict) -> Path:
    return resolve_path(config.get("received_dir", DEFAULTS["received_dir"]))


def history_path(config: dict) -> Path:
    return resolve_path(config.get("history_db", DEFAULTS["history_db"]))
