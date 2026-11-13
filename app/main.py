"""Entry point: the DNSMuggle transfer and detection lab."""

from __future__ import annotations

import sys


def main() -> int:
    from .lab_main import main as lab_main

    return lab_main()


if __name__ == "__main__":
    sys.exit(main())