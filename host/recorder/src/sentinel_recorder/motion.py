from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from sentinel_recorder.config import MotionSettings


@dataclass(frozen=True)
class MotionResult:
    changed_percent: float
    is_motion: bool


class MotionDetector:
    """Compare downscaled greyscale frames to a running-average background."""

    def __init__(self, settings: MotionSettings) -> None:
        self.settings = settings
        self.background: Image.Image | None = None
        self._streak = 0
        self._coverage: Image.Image | None = None
        threshold = settings.pixel_threshold
        self._lut = [255 if value > threshold else 0 for value in range(256)]

    def reset(self) -> None:
        self.background = None
        self._streak = 0

    def feed(self, jpeg_bytes: bytes) -> MotionResult | None:
        frame = self._decode(jpeg_bytes)
        if frame is None:
            return None
        frame = frame.filter(ImageFilter.GaussianBlur(1))
        if self.background is None:
            self.background = frame
            self._streak = 0
            return MotionResult(0.0, False)

        diff = ImageChops.difference(frame, self.background)
        coverage = self._mask(frame.size)
        diff = ImageChops.multiply(diff, coverage)
        self.background = Image.blend(self.background, frame, self.settings.background_alpha)

        changed = diff.point(self._lut).histogram()[255]
        unmasked = coverage.histogram()[255]
        changed_percent = (changed / unmasked) * 100.0 if unmasked else 0.0
        if changed_percent >= self.settings.min_area_percent:
            self._streak += 1
        else:
            self._streak = 0
        return MotionResult(changed_percent, self._streak >= self.settings.trigger_frames)

    def _decode(self, jpeg_bytes: bytes) -> Image.Image | None:
        try:
            image = Image.open(BytesIO(jpeg_bytes))
        except Exception:
            return None
        try:
            if image.width < 1 or image.height < 1:
                return None
            width = self.settings.analysis_width
            height = max(1, width * image.height // image.width)
            image.draft("L", (width, height))
            grey = image.convert("L")
            if grey.size != (width, height):
                grey = grey.resize((width, height))
            return grey
        except Exception:
            return None
        finally:
            image.close()

    def _mask(self, size: tuple[int, int]) -> Image.Image:
        if self._coverage is not None and self._coverage.size == size:
            return self._coverage
        coverage = Image.new("L", size, 255)
        if self.settings.masks:
            draw = ImageDraw.Draw(coverage)
            width, height = size
            for x0, y0, x1, y1 in self.settings.masks:
                left = _clamp(int(x0 * width), 0, width)
                top = _clamp(int(y0 * height), 0, height)
                right = _clamp(int(x1 * width), 0, width)
                bottom = _clamp(int(y1 * height), 0, height)
                if right > left and bottom > top:
                    draw.rectangle([left, top, right - 1, bottom - 1], fill=0)
        self._coverage = coverage
        return coverage


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
