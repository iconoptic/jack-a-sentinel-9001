from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from threading import Event

import httpx

from sentinel_recorder.config import Camera, RecorderSettings

logger = logging.getLogger(__name__)

_SKIP = object()


@dataclass(frozen=True)
class GoodFrame:
    timestamp: float
    jpeg: bytes


@dataclass(frozen=True)
class BadFrame:
    timestamp: float


@dataclass(frozen=True)
class SourceDown:
    timestamp: float


SourceItem = GoodFrame | BadFrame | SourceDown


def is_valid_jpeg(data: bytes) -> bool:
    return len(data) >= 4 and data.startswith(b"\xff\xd8") and b"\xff\xd9" in data[-16:]


def boundary_from_content_type(header: str) -> str:
    for part in header.split(";")[1:]:
        piece = part.strip()
        name, sep, value = piece.partition("=")
        if sep != "=" or name.strip().lower() != "boundary":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if not value:
            break
        return value
    raise ValueError("content type has no boundary")


class MultipartParser:
    """Pull JPEG part bodies out of a multipart stream fed in arbitrary chunks."""

    def __init__(self, boundary: str) -> None:
        self.marker = b"--" + boundary.encode("ascii")
        self.buf = bytearray()
        self.state = "seek"
        self.content_length: int | None = None

    def feed(self, data: bytes) -> list[bytes]:
        if data:
            self.buf.extend(data)
        if self.state == "done":
            return []
        parts: list[bytes] = []
        while self.state != "done":
            if self.state == "seek":
                if not self._seek():
                    break
            elif self.state == "headers":
                if not self._headers():
                    break
            elif self.state == "body":
                body = self._body()
                if body is None:
                    break
                if body is not _SKIP:
                    parts.append(body)  # type: ignore[arg-type]
            else:
                break
        return parts

    def _seek(self) -> bool:
        idx = self.buf.find(self.marker)
        if idx < 0:
            keep = len(self.marker) - 1
            if keep > 0 and len(self.buf) > keep:
                del self.buf[:-keep]
            elif keep <= 0:
                self.buf.clear()
            return False
        del self.buf[: idx + len(self.marker)]
        self.state = "headers"
        return True

    def _headers(self) -> bool:
        if self.buf.startswith(b"--"):
            self.state = "done"
            self.buf.clear()
            return False
        newline = self.buf.find(b"\n")
        if newline < 0:
            return False
        rest = self.buf[newline + 1 :]
        header_end = rest.find(b"\r\n\r\n")
        separator = 4
        if header_end < 0:
            header_end = rest.find(b"\n\n")
            separator = 2
        if header_end < 0:
            return False
        header_blob = bytes(rest[:header_end])
        del self.buf[: newline + 1 + header_end + separator]
        self.content_length = _content_length(header_blob)
        self.state = "body"
        return True

    def _body(self) -> bytes | object | None:
        if self.content_length is not None:
            if len(self.buf) < self.content_length:
                return None
            body = bytes(self.buf[: self.content_length])
            del self.buf[: self.content_length]
            self.content_length = None
            self.state = "seek"
            return body
        idx = self.buf.find(self.marker)
        if idx < 0:
            return None
        end = idx
        if end >= 2 and self.buf[end - 2 : end] == b"\r\n":
            end -= 2
        elif end >= 1 and self.buf[end - 1 : end] == b"\n":
            end -= 1
        body = bytes(self.buf[:end])
        del self.buf[:idx]
        self.state = "seek"
        return body


def iter_frames(
    camera: Camera,
    recorder: RecorderSettings,
    token: str,
    stop: Event,
) -> Iterator[SourceItem]:
    """Yield frames from ``/stream`` or ``/snapshot`` until ``stop`` is set.

    Connect failures, non-200 responses, and a stream that ends are logged once
    and retried with backoff 1, 2, 4, … 30 seconds. HTTP 401 logs
    "stream token rejected" and retries every 30 seconds.
    """
    if not token:
        logger.error("missing stream token for camera %s", camera.id)
        while not stop.wait(30):
            pass
        return

    headers = {"Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(
        connect=recorder.connect_timeout_seconds,
        read=recorder.read_timeout_seconds,
        write=recorder.connect_timeout_seconds,
        pool=recorder.connect_timeout_seconds,
    )
    backoff = 1.0
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        while not stop.is_set():
            started = time.monotonic()
            try:
                if recorder.source == "snapshot":
                    outcome = yield from _read_snapshot(client, camera, headers)
                else:
                    outcome = yield from _read_stream(client, camera, headers, stop)
            except Exception as exc:
                logger.warning("%s stream error %s", camera.frigate_name, type(exc).__name__)
                yield SourceDown(time.time())
                outcome = "retry"
            if stop.is_set() or outcome == "stop":
                return
            if outcome == "unauthorized":
                if stop.wait(30):
                    return
                continue
            if outcome == "snapshot":
                backoff = 1.0
                remaining = (1.0 / recorder.snapshot_fps) - (time.monotonic() - started)
                if remaining > 0 and stop.wait(remaining):
                    return
                continue
            if outcome == "ended":
                backoff = 1.0
            if stop.wait(backoff):
                return
            backoff = min(backoff * 2, 30.0)


def _read_stream(
    client: httpx.Client,
    camera: Camera,
    headers: dict[str, str],
    stop: Event,
) -> Iterator[SourceItem]:
    url = f"http://{camera.static_ip}/stream"
    with client.stream("GET", url, headers=headers) as response:
        kind = _status_kind(camera, response.status_code)
        if kind != "ok":
            yield SourceDown(time.time())
            return kind
        boundary = boundary_from_content_type(response.headers.get("content-type", ""))
        parser = MultipartParser(boundary)
        for chunk in response.iter_bytes():
            if stop.is_set():
                return "stop"
            yield from _parts_to_items(parser.feed(chunk))
    logger.info("%s stream ended", camera.frigate_name)
    yield SourceDown(time.time())
    return "ended"


def _read_snapshot(
    client: httpx.Client,
    camera: Camera,
    headers: dict[str, str],
) -> Iterator[SourceItem]:
    url = f"http://{camera.static_ip}/snapshot"
    response = client.get(url, headers=headers)
    kind = _status_kind(camera, response.status_code)
    if kind != "ok":
        yield SourceDown(time.time())
        return kind
    body = response.content
    timestamp = time.time()
    if is_valid_jpeg(body):
        yield GoodFrame(timestamp, body)
    else:
        yield BadFrame(timestamp)
    return "snapshot"


def _parts_to_items(parts: list[bytes]) -> Iterator[SourceItem]:
    for body in parts:
        timestamp = time.time()
        if is_valid_jpeg(body):
            yield GoodFrame(timestamp, body)
        else:
            yield BadFrame(timestamp)


def _status_kind(camera: Camera, status: int) -> str:
    if status == 401:
        logger.warning("%s stream token rejected", camera.frigate_name)
        return "unauthorized"
    if status != 200:
        logger.warning("%s stream HTTP %s", camera.frigate_name, status)
        return "retry"
    return "ok"


def _content_length(header_blob: bytes) -> int | None:
    text = header_blob.decode("latin-1", errors="replace")
    for line in text.splitlines():
        name, sep, value = line.partition(":")
        if sep == ":" and name.strip().lower() == "content-length":
            raw = value.strip()
            if raw.isascii() and raw.isdigit():
                return int(raw)
            return None
    return None
