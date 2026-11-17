#!/usr/bin/env python3
"""Bootstrap the source quick start without installing any dependencies."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from contitext.onboarding import main

if __name__ == "__main__":
    main(["--output", str(root / ".env"), *sys.argv[1:]])
