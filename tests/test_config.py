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


def test_legacy_lab_data_is_copied_once_without_overwriting(tmp_path, monkeypatch):
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "received").mkdir(parents=True)
    (old / "config.json").write_text('{"delay": 0.2}', encoding="utf-8")
    (old / "history.db").write_bytes(b"legacy history")
    (old / "received" / "file.txt").write_text("original", encoding="utf-8")
    new.mkdir()
    (new / "history.db").write_bytes(b"existing history")
    monkeypatch.setattr(config, "LEGACY_APP_DIR", old)
    monkeypatch.setattr(config, "APP_DIR", new)
    monkeypatch.setattr(config, "CONFIG_PATH", new / "config.json")

    assert config.load_config(new / "config.json")["delay"] == 0.2
    assert (new / "history.db").read_bytes() == b"existing history"
    assert (new / "received" / "file.txt").read_text(encoding="utf-8") == "original"
    (new / "received" / "file.txt").unlink()
    config.load_config(new / "config.json")
    assert not (new / "received" / "file.txt").exists()


def test_migration_copies_custom_relative_paths(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    (old / "custom" / "inbox").mkdir(parents=True)
    (old / "custom" / "inbox" / "a.txt").write_text("received", encoding="utf-8")
    (old / "custom" / "history.db").write_bytes(b"history")
    (old / "config.json").write_text(json.dumps({
        "history_db": "custom/history.db", "received_dir": "custom/inbox",
    }), encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_APP_DIR", old)
    monkeypatch.setattr(config, "APP_DIR", new)
    monkeypatch.setattr(config, "CONFIG_PATH", new / "config.json")

    loaded = config.load_config(new / "config.json")
    assert config.history_path(loaded).read_bytes() == b"history"
    assert (config.received_dir(loaded) / "a.txt").read_text(encoding="utf-8") == "received"
    assert (new / ".lab-migration-v1").exists()


def test_failed_copy_is_retryable_and_never_publishes_partial_file(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "config.json").write_text('{"history_db": "custom.db"}', encoding="utf-8")
    (old / "custom.db").write_bytes(b"complete history")
    monkeypatch.setattr(config, "LEGACY_APP_DIR", old)
    monkeypatch.setattr(config, "APP_DIR", new)
    monkeypatch.setattr(config, "CONFIG_PATH", new / "config.json")
    original_copy = config.shutil.copy2

    def interrupted_copy(source, destination):
        if source == old / "custom.db":
            destination.write_bytes(b"partial")
            raise OSError("disk full")
        return original_copy(source, destination)

    monkeypatch.setattr(config.shutil, "copy2", interrupted_copy)
    loaded = config.load_config(new / "config.json")
    assert not (new / "custom.db").exists()
    assert not (new / ".lab-migration-v1").exists()
    assert config.history_path(loaded).read_bytes() == b"complete history"
    assert any("disk full" in message for message in config.MIGRATION_WARNINGS)

    monkeypatch.setattr(config.shutil, "copy2", original_copy)
    loaded = config.load_config(new / "config.json")
    assert config.history_path(loaded) == new / "custom.db"
    assert (new / "custom.db").read_bytes() == b"complete history"
    assert (new / ".lab-migration-v1").exists()
    assert not config.MIGRATION_WARNINGS


def test_migration_preserves_existing_custom_destination(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "config.json").write_text('{"history_db": "custom.db"}', encoding="utf-8")
    (old / "custom.db").write_bytes(b"old")
    (new / "custom.db").write_bytes(b"new")
    monkeypatch.setattr(config, "LEGACY_APP_DIR", old)
    monkeypatch.setattr(config, "APP_DIR", new)
    monkeypatch.setattr(config, "CONFIG_PATH", new / "config.json")

    loaded = config.load_config(new / "config.json")
    assert config.history_path(loaded).read_bytes() == b"new"
    assert (old / "custom.db").read_bytes() == b"old"


def test_failed_legacy_config_read_is_visible_and_retryable(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "config.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_APP_DIR", old)
    monkeypatch.setattr(config, "APP_DIR", new)
    monkeypatch.setattr(config, "CONFIG_PATH", new / "config.json")

    config.load_config(new / "config.json")
    assert config.MIGRATION_WARNINGS
    assert not (new / ".lab-migration-v1").exists()
    assert not (new / "config.json").exists()
    (old / "config.json").write_text('{"delay": 0.3}', encoding="utf-8")
    assert config.load_config(new / "config.json")["delay"] == 0.3
    assert (new / ".lab-migration-v1").exists()


def test_failed_received_copy_uses_original_and_retries(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    (old / "inbox").mkdir(parents=True)
    (old / "config.json").write_text('{"received_dir": "inbox"}', encoding="utf-8")
    (old / "inbox" / "a.txt").write_text("original", encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_APP_DIR", old)
    monkeypatch.setattr(config, "APP_DIR", new)
    monkeypatch.setattr(config, "CONFIG_PATH", new / "config.json")
    original_copy = config.shutil.copy2

    def interrupted_copy(source, destination):
        if source == old / "inbox" / "a.txt":
            destination.write_text("partial", encoding="utf-8")
            raise OSError("copy interrupted")
        return original_copy(source, destination)

    monkeypatch.setattr(config.shutil, "copy2", interrupted_copy)
    loaded = config.load_config(new / "config.json")
    assert config.received_dir(loaded) == old / "inbox"
    assert (config.received_dir(loaded) / "a.txt").read_text(encoding="utf-8") == "original"
    assert not (new / "inbox" / "a.txt").exists()
    assert not (new / ".lab-migration-v1").exists()
    assert any("copy interrupted" in message for message in config.MIGRATION_WARNINGS)

    monkeypatch.setattr(config.shutil, "copy2", original_copy)
    loaded = config.load_config(new / "config.json")
    assert (config.received_dir(loaded) / "a.txt").read_text(encoding="utf-8") == "original"
    assert (new / ".lab-migration-v1").exists()


def test_existing_config_and_explicit_path_keep_priority(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "config.json").write_text('{"history_db": "old.db"}', encoding="utf-8")
    (old / "new.db").write_bytes(b"original")
    (new / "config.json").write_text('{"history_db": "new.db"}', encoding="utf-8")
    other = tmp_path / "other.json"
    other.write_text('{"delay": 0.4}', encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_APP_DIR", old)
    monkeypatch.setattr(config, "APP_DIR", new)
    monkeypatch.setattr(config, "CONFIG_PATH", new / "config.json")

    assert config.load_config(other)["delay"] == 0.4
    assert not (new / ".lab-migration-v1").exists()
    loaded = config.load_config(new / "config.json")
    assert config.history_path(loaded).read_bytes() == b"original"
    assert not (new / "old.db").exists()
