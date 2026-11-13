"""Native desktop window for the bundled defensive workbench."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import __version__
from ..runtime import set_app_user_model_id
from .server import serve
from .service import WorkbenchService

WEB_ROOT = Path(__file__).resolve().parent / "web"
ICON = Path(__file__).resolve().parent.parent / "assets" / "dnsmuggle-icon.ico"
WINDOW_TITLE = "DNSMuggle"
START_WIDTH = 1180
START_HEIGHT = 760
MIN_WIDTH = 820
MIN_HEIGHT = 520


def _import_webview():
    try:
        import webview
    except ImportError:
        return None
    return webview


def main() -> int:
    if not (WEB_ROOT / "index.html").is_file():
        print("The workbench interface files are missing from this install.",
              file=sys.stderr)
        return 1
    webview = _import_webview()
    if webview is None:
        print(
            "DNSMuggle needs pywebview for its desktop interface.\n"
            "Install it with:  python -m pip install pywebview\n"
            "Linux also needs the WebKitGTK runtime "
            "(Debian/Ubuntu: sudo apt install python3-gi gir1.2-webkit2-4.1).\n"
            "The original lab transfer tools remain available with "
            "`python -m app.lab_main`.",
            file=sys.stderr,
        )
        return 1

    set_app_user_model_id(__version__)
    try:
        service = WorkbenchService()
    except Exception as exc:  # Data directory or database initialization failed.
        print(f"Cannot initialize the workbench data store: {exc}", file=sys.stderr)
        return 1
    try:
        server, thread = serve(service, WEB_ROOT)
    except Exception as exc:  # Socket startup errors vary across platforms.
        service.close()
        print(f"Cannot start the local workbench bridge: {exc}", file=sys.stderr)
        return 1
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.create_window(
            WINDOW_TITLE,
            server.url,
            width=START_WIDTH,
            height=START_HEIGHT,
            min_size=(MIN_WIDTH, MIN_HEIGHT),
            background_color="#101010",
            text_select=True,
            zoomable=False,
            confirm_close=False,
        )
        webview.start(private_mode=True, icon=str(ICON) if ICON.is_file() else None)
    except Exception as exc:  # noqa: BLE001 - native backend failures vary
        print(f"Cannot start the desktop workbench: {exc}", file=sys.stderr)
        print(
            "Windows needs the Microsoft Edge WebView2 runtime; Linux needs "
            "WebKitGTK. The original lab tools remain available with "
            "`python -m app.lab_main`.",
            file=sys.stderr,
        )
        return 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())