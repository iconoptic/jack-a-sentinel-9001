from __future__ import annotations

from sentinel_recorder.config import MotionSettings
from sentinel_recorder.motion import MotionDetector
from images import SQUARE_MASK, grey_image, jpeg_bytes, with_noise, with_square


def test_identical_frames_are_not_motion() -> None:
    detector = MotionDetector(MotionSettings())
    frame = jpeg_bytes(grey_image())
    first = detector.feed(frame)
    assert first is not None and first.is_motion is False
    for _ in range(4):
        result = detector.feed(frame)
        assert result is not None
        assert result.changed_percent == 0
        assert result.is_motion is False


def test_noise_is_not_motion() -> None:
    base = grey_image()
    detector = MotionDetector(MotionSettings())
    assert detector.feed(jpeg_bytes(base)) is not None
    for seed in (1, 2, 3):
        result = detector.feed(jpeg_bytes(with_noise(base, seed)))
        assert result is not None
        assert result.is_motion is False


def test_square_triggers_after_exactly_trigger_frames() -> None:
    settings = MotionSettings(trigger_frames=2)
    detector = MotionDetector(settings)
    base = grey_image()
    square = jpeg_bytes(with_square(base))
    assert detector.feed(jpeg_bytes(base)).is_motion is False
    assert detector.feed(jpeg_bytes(base)).is_motion is False
    first = detector.feed(square)
    second = detector.feed(square)
    assert first is not None and first.is_motion is False
    assert second is not None and second.is_motion is True
    assert second.changed_percent >= settings.min_area_percent


def test_mask_over_square_suppresses_motion() -> None:
    detector = MotionDetector(MotionSettings(masks=SQUARE_MASK))
    base = grey_image()
    square = jpeg_bytes(with_square(base))
    detector.feed(jpeg_bytes(base))
    for _ in range(4):
        result = detector.feed(square)
        assert result is not None
        assert result.is_motion is False


def test_reset_seeds_the_next_frame() -> None:
    settings = MotionSettings(trigger_frames=1)
    detector = MotionDetector(settings)
    base = grey_image()
    first = detector.feed(jpeg_bytes(base))
    assert first is not None and first.is_motion is False
    detector.reset()
    result = detector.feed(jpeg_bytes(with_square(base)))
    assert result is not None and result.is_motion is False


def test_truncated_jpeg_is_none() -> None:
    detector = MotionDetector(MotionSettings())
    whole = jpeg_bytes(grey_image())
    assert detector.feed(whole[:32]) is None
