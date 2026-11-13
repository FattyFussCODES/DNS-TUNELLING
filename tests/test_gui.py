"""Regressions for server presets, Settings and rolling GUI logs."""

import gc
import tkinter as tk
from tkinter import ttk

import pytest

from app import config
from app.gui.receive_tab import ReceiveTab
from app.gui.send_tab import SendTab
from app.gui.settings_tab import SettingsTab


@pytest.fixture(scope="module")
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    window.withdraw()
    yield window
    window.destroy()
    gc.collect()


def test_presets_do_not_include_personal_endpoints(root):
    cfg = dict(config.DEFAULTS, server="192.0.2.10", port=12345, mode="Same Wi-Fi")
    tab = SendTab(root, config=cfg)
    assert tuple(tab.preset_box.cget("values")) == ("Loopback", "Custom")
    assert tab.preset_var.get() == "Custom"
    assert tab.server_var.get() == "192.0.2.10"
    assert tab.port_var.get() == "12345"
    assert tab._mode_for("192.0.2.10") == "Same Wi-Fi"
    tab.preset_var.set("Loopback")
    tab._on_preset()
    assert tab.server_var.get() == "127.0.0.1"
    assert tab.port_var.get() == "5353"
    tab.apply_config(cfg)
    assert tab.preset_var.get() == "Custom"
    assert tab.server_var.get() == "192.0.2.10"


def test_settings_has_no_peer_tools(root):
    tab = SettingsTab(root, config=dict(config.DEFAULTS))
    labels = [widget.cget("text") for widget in tab.winfo_children()
              if isinstance(widget, ttk.LabelFrame)]
    assert "Peer tools" not in labels
    assert "Transport mode" in labels and "About" in labels
    modes = next(widget for widget in tab.winfo_children()
                 if isinstance(widget, ttk.LabelFrame) and widget.cget("text") == "Transport mode")
    options = [widget.cget("text") for widget in modes.winfo_children()
               if isinstance(widget, ttk.Radiobutton)]
    assert options == ["Custom", "Same Wi-Fi", "Public Relay", "Domain (8.8.8.8)"]


@pytest.mark.parametrize("tab_type", [SendTab, ReceiveTab])
def test_log_keeps_latest_entries_and_removes_oldest(root, tab_type):
    tab = tab_type(root, config=dict(config.DEFAULTS))
    for i in range(4005):
        tab._log(f"message-{i:04d}")
    lines = tab.log.get("1.0", "end-1c").splitlines()
    assert len(lines) == 4000
    assert lines[0].endswith("message-0005")
    assert lines[-1].endswith("message-4004")
    assert "truncated" not in "\n".join(lines).lower()
    tab._log("final-first\nfinal-second")
    lines = tab.log.get("1.0", "end-1c").splitlines()
    assert len(lines) == 4000
    assert lines[-2].endswith("final-first")
    assert lines[-1] == "final-second"
