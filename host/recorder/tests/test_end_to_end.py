from __future__ import annotations

import hashlib
import logging
import os
import signal
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from sentinel_recorder.config import load_config
from sentinel_recorder.__main__ import _run, run_camera
from sentinel_recorder.storage import Storage
from images import grey_image, jpeg_bytes, with_square

TOKEN = "super-secret-token-value"
BOUNDARY = "sentinel_mjpeg_boundary"


def _config(tmp_path: Path, port: int) -> Path:
    path = tmp_path / "recorder.toml"
    path.write_text(
        f"""
[recorder]
recordings_dir = "{tmp_path.as_posix()}/recordings"
source = "stream"
pre_roll_seconds = 1
post_roll_seconds = 1
max_event_seconds = 900
latest_jpeg_seconds = 0
retain_days = 30
max_disk_gb = 100
connect_timeout_seconds = 2
read_timeout_seconds = 5

[schedule]
enabled = false
timezone = "UTC"

[motion]
trigger_frames = 2

[[cameras]]
frigate_name = "sentinel_a"
id = "a"
static_ip = "127.0.0.1:{port}"
""",
        encoding="utf-8",
    )
    return path


def _part(body: bytes) -> bytes:
    header = (
        f"--{BOUNDARY}\r\n"
        "Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    )
    return header.encode("ascii") + body + b"\r\n"


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _serve(frames: list[bytes] | None, token: str) -> tuple[_Server, int]:
    sent = {"done": False}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            if self.headers.get("Authorization", "") != f"Bearer {token}":
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                return
            if frames is None or sent["done"]:
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                )
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                return
            sent["done"] = True
            payload = b"".join(_part(frame) for frame in frames)
            payload += f"--{BOUNDARY}--\r\n".encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                return

    server = _Server(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name="mjpeg-test", daemon=True)
    thread.start()
    return server, port


def _sums_ok(event_dir: Path) -> bool:
    sums = event_dir / "SHA256SUMS"
    if not sums.is_file():
        return False
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        if hashlib.sha256((event_dir / rel).read_bytes()).hexdigest() != digest:
            return False
    return any((event_dir / "frames").glob("*.jpg"))


def test_one_event_from_local_stream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = grey_image()
    grey = jpeg_bytes(base)
    square = jpeg_bytes(with_square(base))
    frames = [grey, grey, grey, square, square, square, square, grey, grey]
    server, port = _serve(frames, TOKEN)
    monkeypatch.setenv("SENTINEL_STREAM_TOKEN_A", TOKEN)
    cfg = load_config(_config(tmp_path, port))
    storage = Storage(cfg.recorder, cfg.schedule.timezone)
    stop = threading.Event()
    errors: list[BaseException] = []

    def target() -> None:
        try:
            run_camera(cfg.cameras[0], cfg, storage, stop)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=target, name="recorder-test")
    worker.start()
    try:
        root = tmp_path / "recordings"
        found: Path | None = None
        deadline = time.time() + 15
        while time.time() < deadline:
            matches = list(root.glob("sentinel_a/*/*/SHA256SUMS"))
            if matches and _sums_ok(matches[0].parent):
                found = matches[0].parent
                break
            time.sleep(0.05)
        assert found is not None
        assert len(list(root.glob("sentinel_a/*/*"))) == 1
        assert errors == []
    finally:
        stop.set()
        worker.join(timeout=10)
        server.shutdown()
        server.server_close()


def test_worker_failure_returns_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    base = grey_image()
    grey = jpeg_bytes(base)
    square = jpeg_bytes(with_square(base))
    frames = [grey, grey, square, square, square]
    server, port = _serve(frames, TOKEN)
    monkeypatch.setenv("SENTINEL_STREAM_TOKEN_A", TOKEN)
    config = _config(tmp_path, port)

    def fail_write(self, event, seq, ts, jpeg) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Storage, "write_frame", fail_write)

    def _timeout(_signum, _frame) -> None:
        raise TimeoutError("recorder did not exit within 10s")

    previous = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(10)
    try:
        with caplog.at_level(logging.ERROR):
            code = _run([str(config)])
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        server.shutdown()
        server.server_close()
    assert code == 1
    traced = [
        "".join(traceback.format_exception(*record.exc_info))
        for record in caplog.records
        if record.exc_info
    ]
    assert traced
    assert "OSError" in traced[-1]
    assert "Traceback" in traced[-1]


def test_unwritable_recordings_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    if os.geteuid() == 0:
        pytest.skip("running as root")
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    recordings.chmod(0o555)
    config = _config(tmp_path, 9)
    try:
        code = _run([str(config)])
    finally:
        recordings.chmod(0o755)
    assert code == 2
    assert str(recordings) in capsys.readouterr().err


def test_wrong_token_records_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    server, port = _serve([], TOKEN)
    monkeypatch.setenv("SENTINEL_STREAM_TOKEN_A", "wrong-token")
    cfg = load_config(_config(tmp_path, port))
    storage = Storage(cfg.recorder, cfg.schedule.timezone)
    stop = threading.Event()
    with caplog.at_level(logging.INFO):
        worker = threading.Thread(
            target=run_camera,
            args=(cfg.cameras[0], cfg, storage, stop),
            name="recorder-rejected",
        )
        worker.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline and "stream token rejected" not in caplog.text:
                time.sleep(0.05)
        finally:
            stop.set()
            worker.join(timeout=5)
            server.shutdown()
            server.server_close()
    assert "stream token rejected" in caplog.text
    assert "wrong-token" not in caplog.text
    assert TOKEN not in caplog.text
    assert list((tmp_path / "recordings").glob("sentinel_a/*/*")) == []
