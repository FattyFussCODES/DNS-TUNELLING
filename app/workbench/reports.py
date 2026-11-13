"""Research report generation from stored defensive observations.

Text reports are always available. PDF reports are produced only when the
optional ``reportlab`` package is installed; there is no text file renamed to
look like a PDF. PDF content is drawn as literal text, and control characters
from packet-derived names are escaped so they cannot alter the document layout
or be interpreted as markup.
"""

from __future__ import annotations

import importlib.util
import secrets
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .monitor import COOLDOWN_NOTE, COVERAGE_NOTE, RULE_INFO
from .store import (
    ObservationFilter,
    Store,
    WorkbenchError,
    utc_iso,
    utc_now_ms,
)

SCOPE_NOTE = (
    "Lab only: intentionally delivered queries between your own machines. "
    "No packet capture, forwarding, DNS replies, scanning or file "
    "reconstruction."
)

REPORT_DIR_NAME = "reports"
_PDF_MISSING = (
    "PDF reports require the optional reportlab package "
    "(python -m pip install reportlab); generate a text report instead."
)
_HOURS_LABEL = {1: "last 1 hour", 24: "last 24 hours", 168: "last 7 days"}


class ReportUnavailable(WorkbenchError):
    """A requested report format cannot be produced on this installation."""


def reportlab_available() -> bool:
    """True when a real PDF backend is importable."""
    return importlib.util.find_spec("reportlab") is not None


def _clean(value: Any) -> str:
    """Escape control characters in packet-derived text."""
    text = str(value)
    return "".join(
        char
        if char.isprintable() or char == " "
        else char.encode("unicode_escape").decode("ascii")
        for char in text
    )


def _rule_map(rows: list[dict[str, Any]]) -> dict[str, int]:
    values = {rule["id"]: 0 for rule in RULE_INFO}
    for row in rows:
        values[str(row["rule"])] = int(row["count"])
    return values


def _build_text(
    *,
    title: str,
    created_at: str,
    start_ms: int,
    end_ms: int,
    hours: int,
    total: int,
    anomalies: int,
    sources: list[dict[str, Any]],
    rule_counts: dict[str, int],
    sessions: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> str:
    label = _HOURS_LABEL[hours]
    rate = (
        f"{anomalies / total * 100:.2f}% of observed queries"
        if total
        else "not available (no observed queries)"
    )
    lines = [
        "DNSmuggle Research Report",
        f"Type: {title}",
        "=" * 78,
        f"Generated: {created_at}",
        f"Period: {utc_iso(start_ms)} to {utc_iso(end_ms)} UTC ({label})",
        "",
        "Scope",
        "-" * 78,
        SCOPE_NOTE,
        f"Coverage: {COVERAGE_NOTE}",
        "",
        "Summary",
        "-" * 78,
        f"Observed queries: {total}",
        f"Anomalies (distinct queries with at least one rule alert): {anomalies}",
        f"Heuristic flag rate: {rate}",
        "This rate is a heuristic flag rate, not detection accuracy.",
        "",
        "Rule alerts (emitted evidence rows)",
        "-" * 78,
    ]
    lines.extend(
        f"{rule['id']}: {rule_counts.get(rule['id'], 0)}"
        for rule in RULE_INFO
    )
    lines.extend(["", "Sources", "-" * 78])
    if sources:
        lines.extend(f"{_clean(row['source'])}: {row['count']}" for row in sources)
    else:
        lines.append("none")
    lines.extend(["", "Monitoring sessions", "-" * 78])
    if sessions:
        for session in sessions:
            stopped = session["stopped_at"] or "running"
            lines.append(
                f"session {session['id']}: {session['host']}:{session['port']} "
                f"{session['started_at']} to {_clean(stopped)}"
            )
    else:
        lines.append("none in the selected period")
    lines.extend(["", "Rules and limitations", "-" * 78])
    lines.extend(
        f"{rule['title']}: {rule['description']}" for rule in RULE_INFO
    )
    lines.extend(
        [
            COOLDOWN_NOTE,
            "Ordinary DNS names can score above a heuristic threshold; "
            "recorded values are evidence for review, not proof of tunnelling.",
            "",
            f"Observation evidence ({len(observations)} rows)",
            "-" * 78,
        ]
    )
    if not observations:
        lines.append("No observations were stored for this period.")
    for observation in observations:
        lines.append(
            f"[{observation['timestamp']}] {_clean(observation['qname'])}"
        )
        lines.append(
            f"  source={_clean(observation['source'])} "
            f"length={observation['length']} "
            f"entropy={observation['entropy']:.3f} "
            f"warning={'yes' if observation['warning'] else 'no'} "
            f"session={observation['session_id']}"
        )
        if observation["alerts"]:
            for alert in observation["alerts"]:
                lines.append(
                    f"  alert {_clean(alert['rule'])}: "
                    f"{_clean(alert['reason'])}"
                )
        else:
            lines.append(
                "  no recorded alert evidence (the per-rule cooldown may have "
                "suppressed it)"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_pdf(target: Path, title: str, text: str) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise ReportUnavailable(_PDF_MISSING) from exc

    width, height = A4
    margin = 42
    line_height = 11.5
    pdf = canvas.Canvas(str(target), pagesize=A4)
    y = height - margin
    for index, raw in enumerate(text.splitlines()):
        if index == 0:
            pdf.setFont("Helvetica-Bold", 13)
            current_height = 17
        elif raw and set(raw) == {"-"}:
            continue
        else:
            pdf.setFont("Courier", 8.5)
            current_height = line_height
        # drawString paints literal glyphs; no reportlab markup is parsed.
        for chunk in textwrap.wrap(_clean(raw), width=104) or [""]:
            if y < margin + current_height:
                pdf.showPage()
                y = height - margin
                pdf.setFont("Helvetica", 8.5)
            pdf.drawString(margin, y, chunk)
            y -= current_height
        if index == 0:
            y -= 4
    pdf.setTitle(_clean(title))
    pdf.save()


def create_report(
    store: Store,
    data_dir: str | Path,
    hours: int,
    report_format: str,
) -> dict[str, Any]:
    """Generate, persist and describe a report for the selected period."""
    if hours not in _HOURS_LABEL:
        raise ValueError("hours must be 1, 24 or 168")
    if report_format not in {"txt", "pdf"}:
        raise ValueError("format must be 'txt' or 'pdf'")
    if report_format == "pdf" and not reportlab_available():
        raise ReportUnavailable(_PDF_MISSING)

    endpoint_ms = utc_now_ms()
    start_ms = endpoint_ms - hours * 3_600_000
    filters = ObservationFilter(start_ms=start_ms, end_ms=endpoint_ms)
    total, anomalies = store.counts(filters)
    sources = store.source_counts(filters)
    rule_counts = _rule_map(store.rule_counts(filters))
    sessions = store.sessions(start_ms, endpoint_ms, limit=500)
    observations = store.all_observations(filters)

    title = f"DNSmuggle observation report - {_HOURS_LABEL[hours]}"
    created_at = utc_iso(endpoint_ms)
    text = _build_text(
        title=title,
        created_at=created_at,
        start_ms=start_ms,
        end_ms=endpoint_ms,
        hours=hours,
        total=total,
        anomalies=anomalies,
        sources=sources,
        rule_counts=rule_counts,
        sessions=sessions,
        observations=observations,
    )

    folder = Path(data_dir).resolve() / REPORT_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(
        endpoint_ms / 1000, tz=timezone.utc
    ).strftime("%Y%m%d-%H%M%S")
    filename = f"dnsmuggle-report-{stamp}-{secrets.token_hex(3)}.{report_format}"
    target = folder / filename
    try:
        if report_format == "pdf":
            _write_pdf(target, title, text)
        else:
            target.write_text(text, encoding="utf-8")
        report_id = store.add_report(
            created_ms=endpoint_ms,
            title=title,
            report_format=report_format,
            filename=filename,
            path=str(target),
            total_queries=total,
            anomalies=anomalies,
            hours=hours,
        )
    except Exception:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return {
        "id": int(report_id),
        "created_at": created_at,
        "title": title,
        "format": report_format,
        "filename": filename,
        "total_queries": total,
        "anomalies": anomalies,
    }


def report_content(
    store: Store, data_dir: str | Path, report_id: int
) -> dict[str, Any]:
    """Read one known report from the report directory."""
    row = store.get_report(report_id)
    folder = (Path(data_dir).resolve() / REPORT_DIR_NAME).resolve()
    path = Path(row["path"]).resolve()
    if path.parent != folder or not path.is_file():
        raise WorkbenchError("stored report file is missing or outside the report directory")
    text: str | None = None
    if row["format"] == "txt":
        text = path.read_text(encoding="utf-8")
    return {
        "filename": row["filename"],
        "format": row["format"],
        "text": text,
        "path": str(path),
    }