"""Startpunkt: `python -m jimbo` bzw. die gepackte JiimbosPowerApp.exe."""

from __future__ import annotations

import sys

from .app import run


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
