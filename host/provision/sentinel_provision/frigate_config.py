from __future__ import annotations

import re
from pathlib import Path

from sentinel_provision.cameras import CAMERAS, CameraSpec

GO2RTC_STREAM_LINE = (
    '    {name}: "ffmpeg:http://{ip}/stream?token={token_placeholder}#video=h264#hardware"'
)

CAMERA_BLOCK_TEMPLATE = """
  {name}:
    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/{name}
          input_args: preset-rtsp-restream
          roles:
            - detect
            - record
    detect:
      enabled: true
      width: 1280
      height: 720
      fps: 5
    objects:
      track:
        - person
""".strip("\n")


def _section_end(lines: list[str], header: str, *, start: int = 0) -> tuple[int, int]:
    """Return (header_index, index just past the last indented line of that section)."""
    for i in range(start, len(lines)):
        if lines[i].rstrip() == header:
            break
    else:
        raise ValueError(f"config is missing a {header!r} section")
    end = i + 1
    for j in range(i + 1, len(lines)):
        line = lines[j]
        if line.startswith((" ", "\t")) and line.strip() and not line.strip().startswith("#"):
            end = j + 1
        elif line.strip() == "" or line.startswith(" "):
            continue
        else:
            break
    return i, end


def add_camera_to_text(text: str, cam: CameraSpec, *, token_placeholder: str) -> tuple[str, bool]:
    """Insert the go2rtc stream and the camera block for `cam` if absent. Pure text -> text."""
    lines = text.split("\n")
    modified = False

    g_start, _ = _section_end(lines, "go2rtc:")
    s_idx = next((k for k in range(g_start + 1, len(lines)) if lines[k].rstrip() == "  streams:"), None)
    if s_idx is None:
        raise ValueError("config is missing go2rtc.streams")
    s_end = s_idx + 1
    for k in range(s_idx + 1, len(lines)):
        if lines[k].startswith("    ") and lines[k].strip():
            s_end = k + 1
        elif lines[k].strip() == "":
            continue
        else:
            break
    stream_re = re.compile(rf"^    {re.escape(cam.frigate_name)}:")
    if not any(stream_re.match(ln) for ln in lines[s_idx + 1 : s_end]):
        line = GO2RTC_STREAM_LINE.format(
            name=cam.frigate_name, ip=cam.static_ip, token_placeholder=token_placeholder
        )
        lines.insert(s_end, line)
        modified = True

    c_start, c_end = _section_end(lines, "cameras:")
    cam_re = re.compile(rf"^  {re.escape(cam.frigate_name)}:\s*$")
    if not any(cam_re.match(ln) for ln in lines[c_start + 1 : c_end]):
        block = CAMERA_BLOCK_TEMPLATE.format(name=cam.frigate_name).split("\n")
        lines[c_end:c_end] = block
        modified = True

    return "\n".join(lines), modified


def ensure_frigate_camera(
    config_path: Path,
    cam: CameraSpec,
    *,
    token_placeholder: str,
    generated_dir: Path | None = None,
) -> bool:
    """Idempotently add the go2rtc stream and camera block for one Sentinel camera."""
    text, modified = add_camera_to_text(
        config_path.read_text(), cam, token_placeholder=token_placeholder
    )
    if modified:
        config_path.write_text(text)

    if generated_dir is not None:
        generated_dir.mkdir(parents=True, exist_ok=True)
        stream = GO2RTC_STREAM_LINE.format(
            name=cam.frigate_name, ip=cam.static_ip, token_placeholder=token_placeholder
        ).strip()
        fragment = generated_dir / f"{cam.frigate_name}.yaml"
        fragment.write_text(
            "# Fragment written by sentinel-provision (also merged into config.yml)\n"
            f"go2rtc.streams.{stream}\n\n"
            f"cameras:\n{CAMERA_BLOCK_TEMPLATE.format(name=cam.frigate_name)}\n"
        )
    return modified


def render_frigate_config(
    template: str, camera_names: list[str], tokens: dict[str, str] | None = None
) -> str:
    """Template + every requested camera. With `tokens`, fills {FRIGATE_STREAM_TOKEN_*}.

    MQTT placeholders ({FRIGATE_MQTT_*}) are always left for Frigate to fill from its
    environment; only the stream tokens are baked in, because go2rtc stream URLs are not
    reliably substituted from the container environment (host/README.md "Config drift").
    """
    text = template
    for name in camera_names:
        cam = CAMERAS[name]
        text, _ = add_camera_to_text(text, cam, token_placeholder="{" + cam.stream_token_env + "}")
    if tokens:
        for key, value in tokens.items():
            if any(ch in value for ch in "#{}&\n\r \"'"):
                raise ValueError(f"{key} has characters that would break the go2rtc URL")
            text = text.replace("{" + key + "}", value)
    return text
