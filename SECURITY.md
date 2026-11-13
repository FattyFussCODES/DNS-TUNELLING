# Security

Use DNSmuggle only in environments you own or are explicitly authorized to
use. The workbench is a local research tool, not a network-wide monitor or a
replacement for a DNS server. It observes only queries sent to its configured
UDP endpoint and does not reply, forward, or reconstruct files. Detector
results are heuristic and can miss suspicious traffic.

Observation data and reports can contain sensitive query names and source
addresses. Protect the per-user data directory, and review or redact data
before sharing it. Do not include credentials, local configuration, databases,
reports, or received files in source or distribution artifacts.

The legacy transfer lab sends data through DNS queries. Without a password,
Base32 is encoding, not encryption. Run it only between systems you control.

If you discover a vulnerability, avoid posting sensitive details publicly;
contact the project maintainer privately using an available channel and give
them sufficient information to reproduce the issue safely.
