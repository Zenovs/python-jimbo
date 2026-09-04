"""Erzeugt aus einem ASCII-Zeichen das Programmsymbol assets/icon.ico.

Das Design ist ein "J" (für Jiimbo), aufgebaut aus einem Raster von Blöcken
und nach hinten rechts verlängert – dadurch wirkt das Zeichen dreidimensional.
Aufruf aus dem Projektordner:  python tools/make_icon.py
"""

from __future__ import annotations

import struct

# Das Zeichen als Raster: '#' ist ein gefüllter Block.
GLYPH = [
    "..######",
    "....##..",
    "....##..",
    "....##..",
    "....##..",
    "##..##..",
    "##..##..",
    ".#####..",
]

BG = (26, 32, 54)        # dunkelblauer Hintergrund
FRONT = (255, 212, 59)   # Vorderseite, Python-Gelb
SIDE = (176, 138, 26)    # Seitenflächen, dunkler
DEPTH_CELLS = 1.1        # Tiefe der Verlängerung, gemessen in Rasterzellen
SS = 4                   # Kantenglättung: Unterabtastungen pro Achse


def filled(row: int, col: int) -> bool:
    if 0 <= row < len(GLYPH) and 0 <= col < len(GLYPH[row]):
        return GLYPH[row][col] == "#"
    return False


def ascii_logo(depth: int = 3) -> str:
    """Dasselbe Zeichen als ASCII-Grafik, für den Über-Dialog."""
    height, width = len(GLYPH), len(GLYPH[0])
    canvas = [[" "] * (width * 2 + depth) for _ in range(height + depth)]
    cells = [(r, c) for r in range(height) for c in range(width) if filled(r, c)]
    # Erst alle Seitenflächen, dann die Vorderseiten darüber ("Malerverfahren").
    for row, col in cells:
        for step in range(1, depth + 1):
            y, x = row + depth - step, col * 2 + step
            canvas[y][x] = canvas[y][x + 1] = ":"
    for row, col in cells:
        canvas[row + depth][col * 2] = "#"
        canvas[row + depth][col * 2 + 1] = "#"
    return "\n".join("".join(line).rstrip() for line in canvas)


def shade(x: float, y: float) -> tuple[int, int, int] | None:
    """Farbe an der Stelle (x, y) in Rasterkoordinaten, None = Hintergrund."""
    col, row = int(x // 1), int(y // 1)
    if filled(row, col):
        return FRONT
    # Liegt hinter dem Punkt eine Vorderfläche, ist hier eine Seitenfläche.
    steps = 12
    for i in range(1, steps + 1):
        d = DEPTH_CELLS * i / steps
        if filled(int((y + d) // 1), int((x - d) // 1)):
            return SIDE
    return None


def render(size: int) -> bytes:
    """BGRA-Zeilen von unten nach oben, wie es das BMP-Format erwartet."""
    height, width = len(GLYPH), len(GLYPH[0])
    cols = width + DEPTH_CELLS
    rows = height + DEPTH_CELLS
    scale = size / (max(cols, rows) + 1.6)          # Rand rundherum
    off_x = (size - cols * scale) / 2
    off_y = (size - rows * scale) / 2 + DEPTH_CELLS * scale

    out = bytearray()
    for py in range(size - 1, -1, -1):
        for px in range(size):
            r = g = b = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = ((px + (sx + 0.5) / SS) - off_x) / scale
                    y = ((py + (sy + 0.5) / SS) - off_y) / scale
                    colour = shade(x, y) or BG
                    r += colour[0]
                    g += colour[1]
                    b += colour[2]
            n = SS * SS
            out += bytes((b // n, g // n, r // n, 255))
    return bytes(out)


def dib(size: int) -> bytes:
    """32-Bit-DIB samt leerer AND-Maske, wie im ICO-Format vorgesehen."""
    header = struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0
    )
    mask_stride = ((size + 31) // 32) * 4
    return header + render(size) + b"\x00" * (mask_stride * size)


def main() -> None:
    print(ascii_logo())
    sizes = [16, 32, 48, 64, 256]
    images = [dib(s) for s in sizes]
    data = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for size, image in zip(sizes, images):
        data += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset
        )
        offset += len(image)
    data += b"".join(images)
    with open("assets/icon.ico", "wb") as fh:
        fh.write(data)
    print(f"\nassets/icon.ico geschrieben ({len(data)} Bytes, Größen {sizes})")


if __name__ == "__main__":
    main()
