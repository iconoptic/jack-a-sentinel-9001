from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sentinel_provision.cameras import SEC2_USERNAME


def _import_esp_prov(esp_prov_dir: Path, idf_path: Path):
    sys.path.insert(0, str(idf_path / "components" / "protocomm" / "python"))
    sys.path.insert(0, str(esp_prov_dir))
    import prov  # noqa: WPS433
    import security  # noqa: WPS433
    import transport  # noqa: WPS433

    return prov, security, transport


async def provision_camera_ble(
    *,
    ble_name: str,
    ssid: str,
    wifi_password: str,
    bind_json: str,
    pop: str,
    esp_prov_dir: Path,
    idf_path: Path,
    verbose: bool = False,
) -> None:
    """
    Security 2 session, Wi-Fi creds, and sentinel-bind payload over BLE.
    Matches firmware: username ``sentinel``, SRP password = device PoP.
    """
    prov, security_mod, transport_mod = _import_esp_prov(esp_prov_dir, idf_path)

    nu_lookup = {"prov-session": "ff51", "prov-config": "ff52", "proto-ver": "ff53"}
    tp = transport_mod.Transport_BLE(
        service_uuid="021a9004-0382-4aea-bff4-6b3f1c5adfb4",
        nu_lookup=nu_lookup,
    )
    await tp.connect(devname=ble_name)

    sec_patch_ver = 0
    try:
        response = await tp.send_data("proto-ver", "---")
        import json

        info = json.loads(response)
        sec_patch_ver = int(info.get("prov", {}).get("sec_patch_ver", 0))
    except (ValueError, TypeError):
        sec_patch_ver = 0

    sec = security_mod.Security2(sec_patch_ver, SEC2_USERNAME, pop, verbose)

    response = None
    while True:
        request = sec.security_session(response)
        if request is None:
            break
        response = await tp.send_data("prov-session", request)
        if response is None:
            raise RuntimeError("BLE security session failed")

    message = prov.config_set_config_request("wifi", sec, ssid, wifi_password)
    response = await tp.send_data("prov-config", message)
    if prov.config_set_config_response(sec, response) != 0:
        raise RuntimeError("Set Wi-Fi config rejected")

    message = prov.config_apply_config_request("wifi", sec)
    response = await tp.send_data("prov-config", message)
    if prov.config_apply_config_response(sec, response) != 0:
        raise RuntimeError("Apply Wi-Fi config rejected")

    enc_bind = sec.encrypt_data(bind_json.encode("utf-8"))
    bind_msg = enc_bind.decode("latin-1")
    response = await tp.send_data("sentinel-bind", bind_msg)
    if response is None:
        raise RuntimeError("No response from sentinel-bind endpoint")
    raw = response.encode("latin-1") if isinstance(response, str) else response
    plain = sec.decrypt_data(raw)
    if plain.decode("utf-8", errors="replace").strip() != "OK":
        raise RuntimeError(f"sentinel-bind failed: {plain!r}")

    # Poll until connected or failed (same policy as esp_prov wait_wifi_connected).
    for _ in range(12):
        await asyncio.sleep(5)
        message = prov.config_get_status_request("wifi", sec)
        response = await tp.send_data("prov-config", message)
        state = prov.config_get_status_response(sec, response)
        if state == "connected":
            return
        if state == "failed":
            raise RuntimeError("Wi-Fi connection failed after bind")

    raise RuntimeError("Timed out waiting for Wi-Fi connected")


def resolve_esp_prov_paths() -> tuple[Path, Path]:
    esp_dir = os.environ.get("SENTINEL_ESP_PROV_DIR", "")
    idf_path = os.environ.get("SENTINEL_PROV_IDF_PATH") or os.environ.get("IDF_PATH", "")
    if not esp_dir or not idf_path:
        raise SystemExit(
            "Source ~/.config/jack-sentinel/env.sh (or set SENTINEL_ESP_PROV_DIR and "
            "SENTINEL_PROV_IDF_PATH). Run scripts/install-esp-prov.sh first."
        )
    esp_prov_dir = Path(esp_dir)
    idf = Path(idf_path)
    script = esp_prov_dir / "esp_prov.py"
    if not script.is_file():
        raise SystemExit(f"esp_prov not found at {script}")
    if not (idf / "components" / "protocomm" / "python").is_dir():
        raise SystemExit(f"IDF protocomm python missing under {idf}")
    return esp_prov_dir, idf


def run_ble_provision(**kwargs) -> None:
    asyncio.run(provision_camera_ble(**kwargs))
