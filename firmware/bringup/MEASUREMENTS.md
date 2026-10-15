# Phase 1 bench measurements

Fill one row per resolution after a **30 minute** continuous `GET /stream` at bench
Wi-Fi range. Use the serial telemetry line for fps and temperature. Record the JPEG
quality from menuconfig (`Sentinel bringup` → JPEG quality) or the `jpeg_q=` field in
the log.

Expect sensor PID **0x3660** (OV3660). If not, stop Wave B and see
[docs/phases/README.md](../../docs/phases/README.md) (Grok resolution escalation).

| Resolution | Target size | JPEG quality | Measured fps (serial) | Temp after 30 min (°C) | Stable for product? (Y/N) | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| VGA | 640×480 | | | | | |
| SVGA | 800×600 | | | | | |
| HD | 1280×720 | | | | | |
| UXGA | 1600×1200 (or max stable) | | | | | |

**24 h soak:** one resolution (usually HD) streams continuously; note any brownouts,
Wi-Fi drops, or thermal throttling in Notes.
