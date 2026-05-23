"""Minimal .env loader (no external dependency).

Reads KEY=VALUE lines from a .env file next to this module into os.environ,
without clobbering variables already set in the real environment.
"""

import os
from pathlib import Path


def load_env(filename=".env"):
    path = Path(__file__).resolve().parent / filename
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
