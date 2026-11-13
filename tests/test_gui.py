"""Regressions for server presets, Settings and rolling GUI logs."""

import gc
import socket
import time

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk
from pathlib import Path

from app.gui.main_window import MainWindow
from app.gui import send_tab


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


@pytest.fixture
def main_window(root, tmp_path, monkeypatch):
    cfg = dict(
        config.DEFAULTS,
        server="127.0.0.1",
        history_db=str(tmp_path / "history.db"),
        received_dir=str(tmp_path / "received"),
    )
    monkeypatch.setattr(config, "load_config", lambda: cfg.copy())
    window = tk.Toplevel(root)
    window.withdraw()
    app = MainWindow(window)
    yield app
    app.send_tab.shutdown()
    worker = app.send_tab._worker
    if worker is not None:
        worker.join(timeout=5)
    app._on_close()


def _free_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_gui(window, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.update()
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("Timed out waiting for GUI transfer")


def _button_with_text(widget, text):
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == text:
            return child
        found = _button_with_text(child, text)
        if found is not None:
            return found
    return None


def test_main_window_sidebar_navigates_all_five_pages(main_window):
    app = main_window
    pages = ("Send", "Receive", "History", "Detector", "Settings")
    assert tuple(app._pages) == pages
    assert len(app.notebook.tabs()) == len(pages)
    for name in pages:
        page = app._pages[name]
        button, _ = app._nav_buttons[str(page)]
        button.invoke()
        app.root.update()
        assert app.notebook.select() == str(page)
        assert button.cget("style") == "Selected.Nav.TButton"
        assert all(
            other.cget("style") == "Nav.TButton"
            for key, (other, _) in app._nav_buttons.items()
            if key != str(page)
        )


def test_detector_shares_receiver_and_gui_loopback_transfer(main_window, tmp_path, monkeypatch):
    app = main_window
    receiver = app.receive_tab
    detector = app.detector_tab
    sender = app.send_tab
    port = _free_udp_port()
    receiver.host_var.set("127.0.0.1")
    receiver.port_var.set(str(port))
    sender.server_var.set("127.0.0.1")
    sender.port_var.set(str(port))

    # Starting the detector starts the receiver's listener, not a second socket.
    detector.start_button.invoke()
    listener = receiver.receiver
    assert listener is not None and listener.running
    assert receiver.listen_port == port
    assert detector.observing
    detector.stop_button.invoke()
    assert not detector.observing
    assert receiver.receiver is listener and listener.running
    detector.start_button.invoke()
    assert detector.observing and receiver.receiver is listener

    data = b"GUI loopback regression: real DNS chunks and ACKs.\n" * 3
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    monkeypatch.setattr(send_tab.filedialog, "askopenfilename", lambda **kwargs: str(source))
    choose = _button_with_text(sender, "Choose file")
    assert choose is not None
    choose.invoke()
    assert sender.file_var.get() == str(source)
    sender.send_button.invoke()
    _wait_for_gui(
        app.root,
        lambda: receiver.last_result is not None
        and sender.send_button.instate(["!disabled"])
        and detector.detector.queries > 0,
    )
    assert receiver.result_vars["filename"].get() == source.name
    assert receiver.result_vars["size_match"].get() == "PASS"
    assert receiver.result_vars["sha256_match"].get() == "PASS"
    recovered = Path(receiver.result_vars["saved"].get())
    assert recovered.parent == tmp_path / "received"
    assert recovered.read_bytes() == data
    assert "Done:" in sender.log.get("1.0", "end-1c")
    assert detector.detector.queries > 0
    detector.stop_button.invoke()
    assert receiver.receiver is listener and listener.running
    receiver.stop_button.invoke()
    assert receiver.receiver is None
