"""Defensive DNS research workbench.

The workbench is metadata-only: it observes queries delivered to an explicitly
started lab endpoint, stores rule evidence, and renders reports. It never sends
DNS replies, reconstructs transferred files, or captures unrelated traffic.
"""

from __future__ import annotations

from .service import WorkbenchService

__all__ = ["WorkbenchService"]