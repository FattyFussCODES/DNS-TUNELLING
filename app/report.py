"""Transfer reports: plain text always, PDF when reportlab is installed.

No fake PDFs: if reportlab is missing, `generate_pdf_report` raises and the
caller keeps the text report.
"""

from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

from . import __version__, config
from .history import History
from .utils import format_size, format_time

SCOPE_NOTE = "Lab only, own machines, own files."
REPORTS_DIR = config.APP_DIR / "reports"


class ReportLabMissing(RuntimeError):
    """reportlab is not installed, so a real PDF cannot be produced."""


def _reports_dir(out_dir: str | Path | None) -> Path:
    folder = Path(out_dir) if out_dir is not None else REPORTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _load(transfer_id: int, history: History | None) -> tuple[dict, History, bool]:
    owns = history is None
    hist = history or History(config.history_path(config.load_config()))
    row = hist.get_transfer(int(transfer_id))
    if row is None:
        if owns:
            hist.close()
        raise ValueError(f"transfer {transfer_id} not found in the history database")
    return row, hist, owns


def _yes_no(value) -> str:
    if value is None:
        return "-"
    return "PASS" if int(value) else "FAIL"


def transfer_lines(row: dict) -> list[str]:
    """The report body, shared by the text and PDF writers."""
    lines = [
        f"DNSmuggle {__version__}",
        f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Transfer id: {row['id']}",
        "",
        "Transfer",
        "--------",
        f"Date: {row['timestamp']}",
        f"Direction: {row['direction']}",
        f"Filename: {row['filename']}",
        f"Size: {format_size(row['size'] or 0)} ({row['size']} bytes)",
        f"SHA256: {row['sha256'] or '-'}",
        f"Session: {row['session'] or '-'}",
        f"Server: {row['server'] or '-'}:{row['port'] if row['port'] is not None else '-'}",
        f"Mode: {row['mode'] or '-'}",
        f"Chunks: {row['chunks'] if row['chunks'] is not None else '-'}",
        f"Time: {format_time(row['time_seconds'] or 0.0)} "
        f"({row['time_seconds']} s)",
        f"Result: {row['result'] or '-'}",
        "",
        "Verification",
        "------------",
        f"Size match: {_yes_no(row['size_match'])}",
        f"SHA256 match: {_yes_no(row['sha256_match'])}",
        f"Saved to: {row['path'] or '-'}",
        "",
        "Log",
        "---",
    ]
    log_lines = (row["log"] or "(no log recorded)").splitlines()
    lines.extend(log_lines[:80])
    if len(log_lines) > 80:
        lines.append(f"... {len(log_lines) - 80} more lines in the GUI log")
    lines.extend(["", SCOPE_NOTE])
    return lines


def _base_name(row: dict) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"report-{int(row['id']):04d}-{stamp}"


def generate_txt_report(
    transfer_id: int,
    history: History | None = None,
    *,
    out_dir: str | Path | None = None,
) -> Path:
    row, hist, owns = _load(transfer_id, history)
    try:
        target = _reports_dir(out_dir) / f"{_base_name(row)}.txt"
        target.write_text("\n".join(transfer_lines(row)) + "\n", encoding="utf-8")
        return target
    finally:
        if owns:
            hist.close()


def generate_pdf_report(
    transfer_id: int,
    history: History | None = None,
    *,
    out_dir: str | Path | None = None,
) -> Path:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ReportLabMissing(
            "PDF reports need reportlab: python -m pip install reportlab "
            "(a .txt report is still available)"
        ) from exc

    row, hist, owns = _load(transfer_id, history)
    try:
        lines = transfer_lines(row)
        target = _reports_dir(out_dir) / f"{_base_name(row)}.pdf"

        pdf = canvas.Canvas(str(target), pagesize=A4)
        width, height = A4
        margin = 42
        line_height = 11.5
        y = height - margin

        for index, raw in enumerate(lines):
            if index == 0:
                pdf.setFont("Helvetica-Bold", 13)
                line_height = 16
            elif raw and set(raw) <= {"-"}:
                pdf.setFont("Helvetica", 9)
                line_height = 10
            else:
                pdf.setFont("Courier", 8.5)
                line_height = 11.5

            for chunk in textwrap.wrap(raw, width=104) or [""]:
                if y < margin + line_height:
                    pdf.showPage()
                    y = height - margin
                    pdf.setFont("Courier", 8.5)
                pdf.drawString(margin, y, chunk)
                y -= line_height
            if index == 0:
                y -= 4
        pdf.setTitle(f"DNSmuggle transfer {row['id']} - {row['filename']}")
        pdf.save()
        return target
    finally:
        if owns:
            hist.close()


def generate_report(
    transfer_id: int,
    history: History | None = None,
    *,
    out_dir: str | Path | None = None,
) -> tuple[Path, str]:
    """PDF when possible, text otherwise. Returns (path, 'pdf'|'txt')."""
    try:
        return generate_pdf_report(transfer_id, history, out_dir=out_dir), "pdf"
    except ReportLabMissing:
        return generate_txt_report(transfer_id, history, out_dir=out_dir), "txt"
