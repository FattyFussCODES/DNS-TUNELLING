# Changelog

## 1.1.0

- Restored the transfer and detection application as the default, with a
  redesigned dark interface and direct access to Send, Receive, History,
  Detector and Settings. The transfer protocol is unchanged.
- Kept the defensive telemetry workbench available separately through
  `dnsmuggle-workbench` and `python -m app.workbench.desktop`.
- Store workbench data and lab defaults in platform-specific per-user data
  directories. PDF reports require the optional `pdf` dependency.
- Made the defensive workbench's `pywebview` dependency optional via the
  `workbench` extra; the default Tkinter application does not require it.
- Corrected migration of legacy data to per-user locations while preserving
  existing destination data and original files.
- Defaulted the transfer receiver to loopback rather than all interfaces.
- Bundle the workbench's browser frontend with the Python package; no frontend
  build tool is required.
