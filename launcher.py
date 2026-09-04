"""Startskript für PyInstaller.

PyInstaller kann ein Paket-`__main__.py` nicht direkt einpacken, weil die
relativen Importe darin dann ins Leere greifen. Deshalb dieser Umweg.
"""

from __future__ import annotations

import sys

from jimbo.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
