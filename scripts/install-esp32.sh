#!/usr/bin/env bash
# One-click ESP32-S3 camera install: build firmware/sentinel, bake this deployment's
# secrets into an encrypted NVS image, and flash everything in one esptool call.
# The board reboots already BOUND: it joins the hidden AP and serves /stream with a static
# IP, MQTT login and stream token. There is no BLE step and no serial-console PoP to copy.
#
#   scripts/install-esp32.sh a                  # build + flash camera a (10.77.0.11)
#   scripts/install-esp32.sh all                # a, b, c in turn (prompts to swap boards)
#   scripts/install-esp32.sh a --port /dev/ttyUSB0 --monitor
#   scripts/install-esp32.sh a --from me@fedora # pull camera secrets from the host first
#
# Options:
#   --port DEV      serial port (auto-detected when exactly one is present)
#   --from USER@H   run scripts/secrets-sync.sh pull USER@H first (REMOTE_REPO=$SENTINEL_REMOTE_REPO)
#   --no-build      reuse firmware/sentinel/build
#   --erase         erase the whole flash first (also forgets any BLE-bound state)
#   --monitor       open the serial monitor afterwards
#   --dry-run       build and prepare the images, print the esptool command, touch no board
#   -y              don't prompt
#
# Secrets come from secrets/ (gitignored): ap.env and cameras/<id>.env. The Fedora host
# generates them (scripts/install-fedora.sh). Per-camera NVS encryption keys are minted
# here on first flash and kept in secrets/cameras/<id>.nvs-keys.bin.
#
# BLE provisioning (sentinel-provision bind) still works for boards flashed without this
# script; this path just skips it.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
require_not_root
umask 077

PORT="" FROM="" BUILD=1 ERASE=0 MONITOR=0 DRY=0 TARGETS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)     PORT="${2:?--port needs a device}"; shift ;;
    --from)     FROM="${2:?--from needs user@host}"; shift ;;
    --no-build) BUILD=0 ;;
    --erase)    ERASE=1 ;;
    --monitor)  MONITOR=1 ;;
    --dry-run)  DRY=1 ;;
    -y|--yes)   export ASSUME_YES=1 ;;
    -h|--help)  sed -n '2,26p' "$0"; exit 0 ;;
    a|b|c)      TARGETS+=("$1") ;;
    sentinel_[abc]) TARGETS+=("${1#sentinel_}") ;;
    all)        TARGETS=(a b c) ;;
    *)          die "Unknown argument: $1 (see --help)" ;;
  esac
  shift
done
((${#TARGETS[@]})) || die "Which camera? Usage: $0 <a|b|c|all> [options]"

FW_DIR="$REPO_ROOT/firmware/sentinel"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- Secrets -----------------------------------------------------------------
if [[ -n "$FROM" ]]; then
  "$REPO_ROOT/scripts/secrets-sync.sh" pull "$FROM" ${SENTINEL_REMOTE_REPO:+"$SENTINEL_REMOTE_REPO"}
fi
if [[ ! -f "$SECRETS_DIR/ap.env" ]]; then
  die "No secrets/ap.env on this machine. Install the Fedora host first, then either
    scripts/install-esp32.sh ${TARGETS[0]} --from you@fedora-host     (pulls them over SSH), or
    scripts/secrets-sync.sh pull you@fedora-host"
fi
for id in "${TARGETS[@]}"; do
  [[ -f "$SECRETS_DIR/cameras/$id.env" ]] || die "Missing secrets/cameras/$id.env (re-sync from the Fedora host)."
done
[[ -n "$(ap_env_get WIFI_BSSID)" && -n "$(ap_env_get CHANNEL)" ]] \
  || die "secrets/ap.env has no CHANNEL/WIFI_BSSID yet. Finish scripts/install-fedora.sh on the host, then re-sync."

# --- ESP-IDF -----------------------------------------------------------------
if [[ ! -f "$SENTINEL_ENV_FILE" ]] || ! grep -q SENTINEL_IDF_PATH "$SENTINEL_ENV_FILE"; then
  confirm "ESP-IDF $ESP_IDF_REF is not installed. Install it now (~1.5 GB)?" \
    || die "ESP-IDF is required. Run scripts/install-esp-idf.sh."
  "$REPO_ROOT/scripts/install-esp-idf.sh"
fi
set +u
# shellcheck source=idf-env.sh
. "$REPO_ROOT/scripts/idf-env.sh" >/dev/null
set -u
have idf.py || die "idf.py not on PATH after sourcing scripts/idf-env.sh"

# --- Build (once for all cameras: the binary is identical, only NVS differs) --
if [[ $BUILD == 1 ]]; then
  info "Building firmware/sentinel"
  (
    cd "$FW_DIR"
    grep -qs 'CONFIG_IDF_TARGET="esp32s3"' sdkconfig || idf.py set-target esp32s3
    idf.py build
  )
fi
[[ -f "$FW_DIR/build/flasher_args.json" ]] || die "No build output in $FW_DIR/build (drop --no-build)."

# --- Partition offsets from the built table ------------------------------------
PT_BIN="$FW_DIR/build/partition_table/partition-table.bin"
read -r NVS_OFF NVS_SIZE KEYS_OFF KEYS_SIZE < <(
  python "$IDF_PATH/components/partition_table/gen_esp32part.py" "$PT_BIN" 2>/dev/null | python -c '
import csv, sys
def size(s):
    s = s.strip()
    mult = {"K": 1024, "M": 1024 * 1024}.get(s[-1:].upper(), 1)
    return int(s.rstrip("kKmM"), 0) * mult
rows = {r[2].strip(): r for r in csv.reader(l for l in sys.stdin if not l.startswith("#") and l.strip())}
for sub in ("nvs", "nvs_keys"):
    if sub not in rows:
        sys.exit("partition table has no %s partition" % sub)
n, k = rows["nvs"], rows["nvs_keys"]
print(n[3].strip(), size(n[4]), k[3].strip(), size(k[4]))
'
)
[[ -n "${NVS_OFF:-}" && -n "${KEYS_OFF:-}" ]] || die "Could not read nvs/nvs_keys from the partition table"

# --- Serial port ---------------------------------------------------------------
pick_port() {
  [[ -n "$PORT" ]] && return 0
  local ports=(/dev/ttyUSB* /dev/ttyACM*)
  local found=()
  for p in "${ports[@]}"; do [[ -e "$p" ]] && found+=("$p"); done
  case ${#found[@]} in
    0) die "No serial port found. Plug the board in (the CH340 USB-C port), or pass --port." ;;
    1) PORT="${found[0]}" ;;
    *) die "Several serial ports (${found[*]}); pass --port." ;;
  esac
}

# --- One camera ----------------------------------------------------------------
flash_one() {
  local id="$1" name="sentinel_$1"
  local keyfile="$SECRETS_DIR/cameras/$id.nvs-keys.bin"
  local csv="$WORK/$id.csv" nvs_bin="$WORK/$id.nvs.bin"

  if [[ $DRY == 1 ]]; then PORT="${PORT:-/dev/ttyUSB0}"; else pick_port; fi
  [[ $DRY == 1 || ( -r "$PORT" && -w "$PORT" ) ]] || die "No access to $PORT. Add yourself to the serial group (uucp on Arch, dialout on Fedora) and log in again."

  info "Camera $id: bind data -> NVS image"
  provision_cli nvs-csv "$name" --out "$csv"

  if [[ ! -f "$keyfile" ]]; then
    info "Camera $id: generating its NVS encryption key"
    python -m esp_idf_nvs_partition_gen generate-key --keyfile "$id.bin" --outdir "$WORK" >/dev/null
    install -m 0600 "$WORK/keys/$id.bin" "$keyfile"
  fi
  python -m esp_idf_nvs_partition_gen encrypt "$csv" "$nvs_bin" "$NVS_SIZE" --inputkey "$keyfile" >/dev/null
  [[ "$(stat -c %s "$keyfile")" == "$KEYS_SIZE" ]] || die "NVS key file is not $KEYS_SIZE bytes"
  shred -u "$csv" 2>/dev/null || rm -f "$csv"

  # esptool arguments: everything idf.py would flash, plus this camera's NVS and key.
  local -a args
  mapfile -t args < <(python - "$FW_DIR/build" "$NVS_OFF" "$nvs_bin" "$KEYS_OFF" "$keyfile" <<'PY'
import json, os, sys
build, nvs_off, nvs_bin, keys_off, keys_bin = sys.argv[1:]
fa = json.load(open(os.path.join(build, "flasher_args.json")))
extra = fa["write_flash_args"]
files = {int(k, 0): os.path.join(build, v) for k, v in fa["flash_files"].items()}
for off, path in ((nvs_off, nvs_bin), (keys_off, keys_bin)):
    if int(off, 0) in files:
        sys.exit("NVS/key offset %s collides with a built image" % off)
    files[int(off, 0)] = path
print("\n".join(extra))
for off in sorted(files):
    print(hex(off))
    print(files[off])
PY
  )

  if [[ $DRY == 1 ]]; then
    ok "Dry run: NVS image ($(stat -c %s "$nvs_bin") bytes @ $NVS_OFF) and key ($KEYS_SIZE bytes @ $KEYS_OFF) are valid"
    info "Would run: esptool --chip esp32s3 -p $PORT write-flash ${args[*]//$WORK/<work>}"
    rm -f "$nvs_bin"
    return 0
  fi
  if [[ $ERASE == 1 ]]; then
    info "Erasing flash on $PORT"
    python -m esptool --chip esp32s3 -p "$PORT" erase-flash
  fi
  info "Flashing camera $id to $PORT"
  python -m esptool --chip esp32s3 -p "$PORT" -b 460800 --before default-reset --after hard-reset \
    write-flash "${args[@]}"
  rm -f "$nvs_bin"

  ok "Camera $id flashed: boots BOUND as $name at $(provision_ip "$id")"
}

provision_ip() { printf '10.77.0.1%s' "$(( $(printf '%d' "'$1") - 96 ))"; }

first=1
for id in "${TARGETS[@]}"; do
  if [[ $first == 0 ]]; then
    [[ "${ASSUME_YES:-0}" == 1 && -n "$PORT" ]] || {
      [[ -t 0 ]] || die "Flashing several boards needs a terminal (or -y with --port)."
      read -r -p "Plug in the board for camera $id, then press Enter... " _
    }
  fi
  first=0
  flash_one "$id"
done

if [[ $MONITOR == 1 ]]; then
  info "Serial monitor (Ctrl-] to exit)"
  (cd "$FW_DIR" && idf.py -p "$PORT" monitor)
fi

[[ $DRY == 1 ]] && exit 0
cat <<EOF

Done. Each board now:
  - joins the hidden AP by SSID + BSSID + channel (see secrets/ap.env), static IP from CONTRACTS.md
  - serves /stream?token=... and publishes MQTT state/telemetry to 10.77.0.1:1883
  - never advertises BLE (it is BOUND). Factory reset: hold BOOT 10 s at power-up, then re-run
    this script.
Label each board with its camera id; nothing else needs writing down.
EOF
