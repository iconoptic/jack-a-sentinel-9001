from __future__ import annotations

import pytest

from sentinel_recorder.source import MultipartParser, boundary_from_content_type, is_valid_jpeg


def _jpeg(payload: bytes) -> bytes:
    return b"\xff\xd8" + payload + b"\x00" * 14 + b"\xff\xd9"


def _encode(parts: list[bytes], boundary: str, content_length: bool) -> bytes:
    chunks: list[bytes] = []
    for body in parts:
        header = f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
        if content_length:
            header += f"Content-Length: {len(body)}\r\n"
        header += "\r\n"
        chunks.append(header.encode("ascii") + body + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)


def _kept(payload: bytes, boundary: str, chunk: int) -> list[bytes]:
    parser = MultipartParser(boundary)
    frames: list[bytes] = []
    for offset in range(0, len(payload), chunk):
        for body in parser.feed(payload[offset : offset + chunk]):
            if is_valid_jpeg(body):
                frames.append(body)
    return frames


@pytest.mark.parametrize("chunk", [1, 7, 4096])
@pytest.mark.parametrize("content_length", [True, False])
def test_parser_reassembles_split_chunks(chunk: int, content_length: bool) -> None:
    boundary = "sentinel_mjpeg_boundary"
    good_a = _jpeg(b"alpha")
    corrupt = b"\xff\xd8this-part-has-no-eoi-marker-nearby"
    good_b = _jpeg(b"beta")
    payload = _encode([good_a, corrupt, good_b], boundary, content_length)
    assert _kept(payload, boundary, chunk) == [good_a, good_b]


def test_quoted_boundary() -> None:
    header = 'multipart/x-mixed-replace; boundary="sentinel_mjpeg_boundary"'
    boundary = boundary_from_content_type(header)
    assert boundary == "sentinel_mjpeg_boundary"
    frame = _jpeg(b"quoted")
    payload = _encode([frame], boundary, content_length=True)
    assert _kept(payload, boundary, 7) == [frame]


def test_malformed_content_length_keeps_next_part() -> None:
    boundary = "sentinel_mjpeg_boundary"
    good = _jpeg(b"kept")
    marker = f"--{boundary}".encode("ascii")
    bad = (
        marker
        + b"\r\nContent-Type: image/jpeg\r\nContent-Length: abc\r\n\r\n"
        + b"not-a-jpeg\r\n"
    )
    good_part = (
        marker
        + f"\r\nContent-Type: image/jpeg\r\nContent-Length: {len(good)}\r\n\r\n".encode("ascii")
        + good
        + b"\r\n"
    )
    payload = bad + good_part + marker + b"--\r\n"
    assert good in MultipartParser(boundary).feed(payload)
    assert _kept(payload, boundary, 1) == [good]


def test_unquoted_boundary_header() -> None:
    header = "multipart/x-mixed-replace; boundary=sentinel_mjpeg_boundary"
    assert boundary_from_content_type(header) == "sentinel_mjpeg_boundary"
