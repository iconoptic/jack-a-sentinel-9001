from __future__ import annotations

import argparse
import sys
from getpass import getpass
from pathlib import Path

from sentinel_provision.ap_env import load_ap_env, normalize_bssid, update_ap_env
from sentinel_provision.bind_payload import bind_payload_json, build_bind_payload
from sentinel_provision.ble_provision import resolve_esp_prov_paths, run_ble_provision
from sentinel_provision.cameras import CAMERAS, DEFAULT_HOST_ID, get_camera
from sentinel_provision.credentials import (
    ensure_mqtt_user_line,
    load_camera_secrets,
    load_or_create_camera_secrets,
    parse_env_file,
    upsert_frigate_stream_token,
    write_private,
)
from sentinel_provision.frigate_config import ensure_frigate_camera, render_frigate_config
from sentinel_provision.init_secrets import init_secrets
from sentinel_provision.mosquitto_config import ensure_acl_block
from sentinel_provision.nvs_image import bind_nvs_csv


def _repo_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    return Path(__file__).resolve().parents[3]


def cmd_bind(args: argparse.Namespace) -> int:
    repo = _repo_root(args.repo_root)
    cam = get_camera(args.camera)
    secrets_dir = repo / "secrets"

    ap_path = args.ap_env or (secrets_dir / "ap.env")
    if not ap_path.is_file():
        print(f"Missing AP secrets: {ap_path}", file=sys.stderr)
        print("Run host/scripts/generate-secrets.sh and configure CHANNEL / WIFI_BSSID.", file=sys.stderr)
        return 1

    ap = load_ap_env(ap_path)
    bssid = args.wifi_bssid or ap.bssid
    if not bssid:
        print(
            "Wi-Fi BSSID required: add WIFI_BSSID=aa:bb:... to secrets/ap.env or pass --wifi-bssid",
            file=sys.stderr,
        )
        return 1
    channel = args.wifi_channel if args.wifi_channel is not None else ap.channel

    creds = load_or_create_camera_secrets(secrets_dir, cam)
    payload = build_bind_payload(
        cam,
        host_id=args.host_id,
        mqtt_password=creds.mqtt_password,
        stream_token=creds.stream_token,
        wifi_bssid=bssid,
        wifi_channel=channel,
    )
    bind_json = bind_payload_json(payload)

    users_path = secrets_dir / "mosquitto" / "users"
    acl_path = secrets_dir / "mosquitto" / "acl"
    frigate_env = secrets_dir / "frigate.env"
    frigate_config = repo / "host" / "frigate" / "config.yml"
    generated_dir = repo / "host" / "frigate" / "generated"

    print(f"Camera {cam.frigate_name} ({cam.static_ip})")
    if args.dry_run:
        print("Dry run — host file updates skipped, BLE skipped.")
        print("Bind JSON:", bind_json)
        return 0

    changed_users = ensure_mqtt_user_line(users_path, cam.mqtt_username, creds.mqtt_password)
    changed_acl = ensure_acl_block(acl_path, cam, repo_root=repo)
    changed_token = upsert_frigate_stream_token(
        frigate_env, cam.stream_token_env, creds.stream_token
    )
    token_ph = "{" + cam.stream_token_env + "}"
    changed_frigate = ensure_frigate_camera(
        frigate_config,
        cam,
        token_placeholder=token_ph,
        generated_dir=generated_dir,
    )

    if changed_users:
        print(f"Updated {users_path}")
    if changed_acl:
        print(f"Updated {acl_path}")
    if changed_token:
        print(f"Updated {frigate_env} ({cam.stream_token_env})")
    if changed_frigate:
        print(f"Updated {frigate_config}")

    print(
        "\nMosquitto: re-hash passwords on Fedora — "
        "sudo host/scripts/hash-mqtt-passwords.sh, copy secrets to /etc/sentinel/mosquitto/, "
        "restart mosquitto.service."
    )
    print(
        "Frigate: copy config + frigate.env to /etc/sentinel/ and restart frigate.service "
        "(or host/scripts/render-frigate-config.sh if go2rtc leaves a literal token placeholder)."
    )

    if args.skip_ble:
        print("Skipping BLE (--skip-ble).")
        return 0

    pop = args.pop
    if not pop:
        pop = getpass("Device Security2 PoP (from serial / masking tape): ")
    ble_name = args.ble_name
    if not ble_name:
        ble_name = input("BLE device name (e.g. SENTINEL-A1B2): ").strip()
    if not ble_name:
        print("BLE name is required unless --skip-ble.", file=sys.stderr)
        return 1

    esp_prov_dir, idf_path = resolve_esp_prov_paths()
    print(f"\nProvisioning {ble_name} over BLE (Security2 user sentinel)...")
    run_ble_provision(
        ble_name=ble_name,
        ssid=ap.ssid,
        wifi_password=ap.psk,
        bind_json=bind_json,
        pop=pop,
        esp_prov_dir=esp_prov_dir,
        idf_path=idf_path,
        verbose=args.verbose,
    )
    print("BLE provisioning finished.")
    return 0


def _camera_names(spec: str) -> list[str]:
    ids = [c.strip() for c in spec.split(",") if c.strip()]
    by_id = {c.camera_id: name for name, c in CAMERAS.items()}
    try:
        return [by_id[i] for i in ids]
    except KeyError as exc:
        raise SystemExit(f"Unknown camera id {exc.args[0]!r}; use a, b and/or c") from exc


def cmd_init(args: argparse.Namespace) -> int:
    repo = _repo_root(args.repo_root)
    cams = [CAMERAS[n] for n in _camera_names(args.cameras)]
    res = init_secrets(repo / "secrets", repo, cams)
    for item in res.created:
        print(f"  generated  {item}")
    for item in res.kept:
        print(f"  kept       {item}")
    print(f"Secrets are in {repo / 'secrets'} (gitignored, mode 0600).")
    return 0


def cmd_ap_set(args: argparse.Namespace) -> int:
    repo = _repo_root(args.repo_root)
    updates: dict[str, str] = {}
    for item in args.assignments:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"expected KEY=VALUE, got {item!r}")
        updates[key] = value
    if "WIFI_BSSID" in updates and updates["WIFI_BSSID"]:
        updates["WIFI_BSSID"] = normalize_bssid(updates["WIFI_BSSID"])
    if updates.get("CHANNEL") not in (None, "1", "6", "11"):
        raise SystemExit("CHANNEL must be 1, 6, or 11")
    changed = update_ap_env(repo / "secrets" / "ap.env", updates)
    print("updated" if changed else "unchanged", repo / "secrets" / "ap.env")
    return 0


def cmd_render_frigate(args: argparse.Namespace) -> int:
    repo = _repo_root(args.repo_root)
    names = _camera_names(args.cameras)
    env = parse_env_file(repo / "secrets" / "frigate.env")
    tokens = {CAMERAS[n].stream_token_env: env.get(CAMERAS[n].stream_token_env, "") for n in names}
    missing = [k for k, v in tokens.items() if not v]
    if missing:
        raise SystemExit(f"secrets/frigate.env lacks {', '.join(missing)}; run `sentinel-provision init`")
    template = (repo / "host" / "frigate" / "config.yml").read_text()
    text = render_frigate_config(template, names, tokens)
    if args.out == "-":
        sys.stdout.write(text)
    else:
        write_private(Path(args.out), text)
    return 0


def cmd_nvs_csv(args: argparse.Namespace) -> int:
    """Everything a board needs to boot BOUND, as nvs_partition_gen CSV. Read-only on secrets."""
    repo = _repo_root(args.repo_root)
    cam = get_camera(args.camera)
    ap = load_ap_env(args.ap_env or (repo / "secrets" / "ap.env"), require_bssid=True)
    creds = load_camera_secrets(repo / "secrets", cam)
    payload = build_bind_payload(
        cam,
        host_id=args.host_id,
        mqtt_password=creds.mqtt_password,
        stream_token=creds.stream_token,
        wifi_bssid=ap.bssid or "",
        wifi_channel=ap.channel,
    )
    bind_payload_json(payload)  # same key-set validation as the BLE path
    write_private(Path(args.out), bind_nvs_csv(payload, wifi_ssid=ap.ssid, wifi_psk=ap.psk))
    print(f"{cam.frigate_name}: {cam.static_ip} on channel {ap.channel}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinel-provision",
        description="Generate host secrets and bind a Sentinel camera over BLE.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (defaults to auto-detect)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Generate all secrets (AP, MQTT, stream tokens); idempotent")
    init.add_argument("--cameras", default="a,b,c", help="Camera ids, comma separated")
    init.set_defaults(func=cmd_init)

    ap_set = sub.add_parser("ap-set", help="Set WIFI_IFACE / CHANNEL / WIFI_BSSID in secrets/ap.env")
    ap_set.add_argument("assignments", nargs="+", metavar="KEY=VALUE")
    ap_set.set_defaults(func=cmd_ap_set)

    render = sub.add_parser("render-frigate", help="Frigate config with every camera and tokens filled in")
    render.add_argument("--cameras", default="a,b,c")
    render.add_argument("--out", default="-", help="Output path, or - for stdout")
    render.set_defaults(func=cmd_render_frigate)

    nvs = sub.add_parser("nvs-csv", help="Bind data as nvs_partition_gen CSV (one-click flash)")
    nvs.add_argument("camera", choices=sorted(CAMERAS))
    nvs.add_argument("--out", required=True)
    nvs.add_argument("--host-id", default=DEFAULT_HOST_ID)
    nvs.add_argument("--ap-env", type=Path, default=None)
    nvs.set_defaults(func=cmd_nvs_csv)

    bind = sub.add_parser("bind", help="Prepare host config and provision one camera")
    bind.add_argument(
        "camera",
        choices=["sentinel_a", "sentinel_b", "sentinel_c"],
        help="Frigate camera name",
    )
    bind.add_argument("--host-id", default=DEFAULT_HOST_ID, help="host_id in bind JSON")
    bind.add_argument("--ap-env", type=Path, default=None, help="Path to secrets/ap.env")
    bind.add_argument("--wifi-bssid", default=None, help="AP BSSID for bind payload")
    bind.add_argument("--wifi-channel", type=int, default=None, help="Override AP channel")
    bind.add_argument("--pop", default="", help="Security2 PoP (SRP password); prompt if empty")
    bind.add_argument("--ble-name", default="", help="BLE advertised name SENTINEL-XXXX")
    bind.add_argument("--skip-ble", action="store_true", help="Only update host secrets/config")
    bind.add_argument("--dry-run", action="store_true", help="Print bind JSON only")
    bind.add_argument("--verbose", action="store_true", help="Verbose esp_prov security logs")
    bind.set_defaults(func=cmd_bind)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
