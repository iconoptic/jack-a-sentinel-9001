from __future__ import annotations

import random
from io import BytesIO

from PIL import Image, ImageDraw


def grey_image() -> Image.Image:
    return Image.new("RGB", (1280, 720), (128, 128, 128))


def with_square(image: Image.Image) -> Image.Image:
    frame = image.copy()
    draw = ImageDraw.Draw(frame)
    draw.rectangle([200, 150, 499, 449], fill=(0, 0, 0))
    return frame


def with_noise(image: Image.Image, seed: int) -> Image.Image:
    rng = random.Random(seed)
    raw = bytearray(image.tobytes())
    for index in range(0, len(raw), 3):
        delta = rng.randint(-3, 3)
        for channel in range(3):
            raw[index + channel] = max(0, min(255, raw[index + channel] + delta))
    return Image.frombytes("RGB", image.size, bytes(raw))


def jpeg_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


# Square on the 1280×720 frame, padded so a 1 px blur at analysis size stays inside.
SQUARE_MASK = ((152 / 1280, 102 / 720, 548 / 1280, 498 / 720),)
