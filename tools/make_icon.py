"""Draw the 24x24 menu icon (a vinyl record) to lyrion_remote/icon.png.

Pure Python so it needs no imaging library: shapes are rendered at 8x and box
filtered down for antialiasing, then written as an RGBA PNG.
"""

import math
import os
import struct
import zlib

SIZE = 24
SS = 8  # supersampling factor

DISC = (28, 28, 34)
GROOVE = (70, 72, 84)
LABEL = (246, 135, 4)
SHINE = (255, 255, 255)


def sample(x, y):
    # Colour (r, g, b, a) at a point in icon pixel coordinates
    cx = cy = SIZE / 2
    dx, dy = x - cx, y - cy
    r = math.hypot(dx, dy)

    if r > 11:
        return (0, 0, 0, 0)
    if r < 1.1:
        return (0, 0, 0, 0)  # spindle hole
    if r < 4.6:
        return LABEL + (255,)

    # A soft highlight sweeping across the upper left of the grooves
    angle = math.atan2(dy, dx)
    shine = max(0.0, math.cos(angle + 2.4)) ** 6 * 0.55

    colour = GROOVE if (7.0 < r < 7.6 or 9.0 < r < 9.6) else DISC
    colour = tuple(int(c + (s - c) * shine) for c, s in zip(colour, SHINE))
    return colour + (255,)


def render():
    pixels = []
    for py in range(SIZE):
        row = []
        for px in range(SIZE):
            acc = [0, 0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    r, g, b, a = sample(px + (sx + 0.5) / SS, py + (sy + 0.5) / SS)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            alpha = acc[3] / (SS * SS)
            if acc[3]:
                row.append(tuple(int(c / acc[3]) for c in acc[:3]) + (int(alpha),))
            else:
                row.append((0, 0, 0, 0))
        pixels.append(row)
    return pixels


def write_png(path, pixels):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in pixels)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "..", "lyrion_remote", "icon.png")
    write_png(out, render())
    print("wrote", os.path.normpath(out))
