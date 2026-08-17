#!/usr/bin/env python3
"""Makine Arıza Takip Sistemi - başlatıcı.

Kullanım:
    python run.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
