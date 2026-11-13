"""Small helpers shared by the protocol, the GUI and the reporters."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(block), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in _SIZE_UNITS:
        if value < 1024 or unit == _SIZE_UNITS[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num_bytes} B"


def format_time(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # negative or NaN
        return "-"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {rest:02.0f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes:02d}m"


def stamp() -> str:
    """Wall-clock HH:MM:SS for log lines."""
    return time.strftime("%H:%M:%S")


def unique_path(directory: str | Path, filename: str, prefix: str = "") -> Path:
    """directory/filename, or "name (1).ext", "name (2).ext" ... if taken."""
    folder = Path(directory)
    name = prefix + filename
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    index = 1
    while True:
        candidate = folder / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1
