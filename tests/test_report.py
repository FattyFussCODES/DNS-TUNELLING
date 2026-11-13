"""Reports: the text file always contains the required fields; PDF is real."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import report
from app.history import History


@pytest.fixture()
def history(tmp_path):
    hist = History(tmp_path / "history.db")
    hist.save_transfer(
        direction="receive",
        filename="secret.txt",
        size=10,
        sha256="a" * 64,
        session="482534",
        server="10.0.0.9",
        port=53,
        mode="Skein",
        chunks=10,
        result="PASS",
        time_seconds=0.42,
        size_match=True,
        sha256_match=True,
        path=str(tmp_path / "received" / "secret.txt"),
        log="[12:00:01] Session 482534: chunk 001 (1 stored)",
        timestamp="2026-11-12 12:00:01",
    )
    yield hist
    hist.close()


def test_txt_report_has_every_required_field(history, tmp_path):
    path = report.generate_txt_report(1, history, out_dir=tmp_path / "reports")
    text = path.read_text(encoding="utf-8")
    assert path.suffix == ".txt"
    for needle in (
        "2026-11-12 12:00:01", "secret.txt", "10 B", "a" * 64, "482534",
        "10.0.0.9:53", "Skein", "Chunks: 10", "Result: PASS",
        "Size match: PASS", "SHA256 match: PASS",
        report.SCOPE_NOTE,
        "chunk 001",
    ):
        assert needle in text, needle


def test_missing_transfer_raises(history, tmp_path):
    with pytest.raises(ValueError):
        report.generate_txt_report(999, history, out_dir=tmp_path)


def test_generate_report_falls_back_to_txt(monkeypatch, history, tmp_path):
    monkeypatch.setattr(report, "generate_pdf_report",
                        lambda *a, **k: (_ for _ in ()).throw(report.ReportLabMissing("no")))
    path, kind = report.generate_report(1, history, out_dir=tmp_path / "reports")
    assert kind == "txt" and path.exists()


def test_pdf_report_is_a_real_pdf(history, tmp_path):
    pytest.importorskip("reportlab")
    path = report.generate_pdf_report(1, history, out_dir=tmp_path / "reports")
    data = Path(path).read_bytes()
    assert path.suffix == ".pdf"
    assert data.startswith(b"%PDF")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 1000
