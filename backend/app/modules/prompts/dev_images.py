"""Simple test pictures for the development image prompts, drawn at seed time.

They are flat shapes the code draws itself, so no picture file is committed and none has an
owner or licence question. They only let the picture mode be tried; real pictures need the
review in docs/RECORDING_MODES.md (Q-G7).
"""

import struct
import zlib
from collections.abc import Callable

WIDTH, HEIGHT = 480, 320

Colour = tuple[int, int, int]
Shape = Callable[[int, int], bool]

SKY: Colour = (186, 222, 240)
GROUND: Colour = (160, 196, 110)
SUN: Colour = (250, 204, 70)
WALL: Colour = (214, 168, 120)
ROOF: Colour = (150, 70, 40)
DOOR: Colour = (110, 60, 30)
TRUNK: Colour = (120, 80, 40)
LEAVES: Colour = (60, 140, 60)
WATER: Colour = (90, 150, 210)
BOAT: Colour = (140, 90, 50)
POT: Colour = (170, 90, 50)
FIRE: Colour = (240, 120, 40)
WOOD: Colour = (100, 70, 40)


def rect(x0: int, y0: int, x1: int, y1: int) -> Shape:
    return lambda x, y: x0 <= x < x1 and y0 <= y < y1


def circle(cx: int, cy: int, r: int) -> Shape:
    return lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def triangle(apex: tuple[int, int], left: tuple[int, int], right: tuple[int, int]) -> Shape:
    """A triangle with a flat base from `left` to `right` and its point at `apex`."""
    (ax, ay), (lx, base), (rx, _) = apex, left, right

    def inside(x: int, y: int) -> bool:
        if not ay <= y <= base:
            return False
        share = (y - ay) / (base - ay)
        return ax + (lx - ax) * share <= x <= ax + (rx - ax) * share

    return inside


SCENES: dict[str, list[tuple[Shape, Colour]]] = {
    # A house with a tree beside it.
    "house": [
        (rect(0, 220, WIDTH, HEIGHT), GROUND),
        (circle(400, 60, 30), SUN),
        (rect(120, 140, 280, 240), WALL),
        (triangle((200, 80), (100, 140), (300, 140)), ROOF),
        (rect(180, 180, 220, 240), DOOR),
        (rect(355, 150, 370, 240), TRUNK),
        (circle(362, 125, 40), LEAVES),
    ],
    # A river with a small boat.
    "river": [
        (rect(0, 150, WIDTH, HEIGHT), GROUND),
        (rect(0, 190, WIDTH, 270), WATER),
        (circle(80, 60, 28), SUN),
        (triangle((240, 196), (180, 228), (300, 228)), BOAT),
        (rect(236, 130, 242, 200), TRUNK),
        (triangle((242, 130), (242, 190), (280, 190)), (245, 245, 235)),
    ],
    # A cooking pot over a fire.
    "cooking": [
        (rect(0, 230, WIDTH, HEIGHT), GROUND),
        (circle(240, 150, 48), POT),
        (rect(200, 96, 280, 108), POT),
        (triangle((210, 196), (190, 250), (235, 250)), FIRE),
        (triangle((240, 186), (215, 250), (265, 250)), FIRE),
        (triangle((270, 196), (245, 250), (290, 250)), FIRE),
        (rect(170, 248, 310, 260), WOOD),
    ],
}


def _pixel(scene: list[tuple[Shape, Colour]], x: int, y: int) -> Colour:
    colour = SKY
    for shape, fill in scene:
        if shape(x, y):
            colour = fill
    return colour


def draw_png(name: str) -> bytes:
    """The named scene as a PNG file."""
    scene = SCENES[name]
    rows = bytearray()
    for y in range(HEIGHT):
        rows.append(0)  # no filter
        for x in range(WIDTH):
            rows.extend(_pixel(scene, x, y))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )
