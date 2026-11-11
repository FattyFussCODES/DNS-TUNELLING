#!/usr/bin/env python3
"""Local roundtrip test: decoder + encoder on loopback, no Mininet.

    python3 test_roundtrip.py

Starts decoder.py on 127.0.0.1:5353, sends examples/secret.txt with
encoder.py, waits for recovered_secret.txt, and checks it matches
the original byte for byte. Cleans up recovered_secret.txt after.
"""
import hashlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ORIGINAL = ROOT / "examples" / "secret.txt"
RECOVERED = ROOT / "recovered_secret.txt"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    decoder = subprocess.Popen(
        [sys.executable, str(ROOT / "decoder.py"),
         "--host", "127.0.0.1", "--port", "5353"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(1.0)
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "encoder.py"), str(ORIGINAL),
             "--server", "127.0.0.1", "--port", "5353", "--delay", "0.05"],
            capture_output=True, text=True, timeout=60,
        )
        print(result.stdout, end="")
        if result.returncode != 0:
            print(result.stderr, end="")
            print("FAIL: encoder exited non-zero")
            return 1

        deadline = time.time() + 10
        while not RECOVERED.exists() and time.time() < deadline:
            time.sleep(0.2)
        if not RECOVERED.exists():
            print("FAIL: recovered_secret.txt was never written")
            return 1
        if sha256(ORIGINAL) == sha256(RECOVERED):
            print("PASS: recovered file matches original (SHA256)")
            return 0
        print("FAIL: recovered file differs from original")
        return 1
    finally:
        decoder.terminate()
        try:
            decoder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            decoder.kill()
        if RECOVERED.exists():
            RECOVERED.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
