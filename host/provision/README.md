# sentinel-provision

Host CLI for one camera at a time: generate MQTT and stream secrets, update
mosquitto ACL / Frigate config, then bind the board over BLE (Security 2 + custom
`sentinel-bind` endpoint). Wire formats are frozen in
[docs/phases/CONTRACTS.md](../../docs/phases/CONTRACTS.md).

## Setup

On the Fedora host (or any machine with BlueZ for live bind):

```bash
source ~/.config/jack-sentinel/env.sh   # or scripts/install-* output
scripts/setup-python-venv.sh            # installs this package editable
```

`esp_prov` comes from `scripts/install-esp-prov.sh` (`$SENTINEL_ESP_PROV_DIR`,
`$SENTINEL_PROV_IDF_PATH`). BLE provisioning needs bleak/cryptography/protobuf in
the repo `.venv`.

Prepare secrets once. `scripts/install-fedora.sh` does all of this; by hand:

```bash
host/scripts/generate-secrets.sh        # sentinel-provision init: SSID, PSK, MQTT, tokens, ACL
host/network/install-ap.sh              # fills WIFI_IFACE, CHANNEL, WIFI_BSSID in secrets/ap.env
```

## One-click flash (no BLE)

`scripts/install-esp32.sh <a|b|c|all>` uses `sentinel-provision nvs-csv` to turn the same
bind data into an encrypted NVS image and flashes it with the firmware. The board boots BOUND.
The BLE flow below is the fallback for boards flashed without secrets, and for re-binding after
a factory reset when you would rather not reflash.

Subcommands: `init` (generate secrets), `ap-set KEY=VALUE` (edit `ap.env`), `render-frigate`
(all cameras, tokens filled), `nvs-csv CAM --out FILE` (bind data for the flasher), `bind CAM`.

## Example — `sentinel_a`

After Phase 1 flash, copy the **PoP** from serial / masking tape. The device
advertises as `SENTINEL-XXXX` (last two Wi‑Fi MAC bytes).

```bash
. .venv/bin/activate
sentinel-provision bind sentinel_a \
  --pop 'YOUR12CHARPOP' \
  --ble-name 'SENTINEL-A1B2'
```

Host-only dry run (no file writes, no BLE):

```bash
sentinel-provision bind sentinel_a --dry-run --wifi-bssid aa:bb:cc:dd:ee:ff
```

Secrets and config only (CI / prep before the board is on the bench):

```bash
sentinel-provision bind sentinel_a --skip-ble --wifi-bssid aa:bb:cc:dd:ee:ff
```

Security 2 uses username **`sentinel`** and the device PoP as the SRP password
(firmware `prov_ble.c`). The CLI sends standard Wi‑Fi credentials, then JSON on
`sentinel-bind`.

## What the command updates

| Path | Change |
| --- | --- |
| `secrets/cameras/<id>.env` | MQTT username/password, stream token |
| `secrets/mosquitto/users` | `cam_<id>:<password>` line |
| `secrets/mosquitto/acl` | topic ACL for that camera |
| `secrets/frigate.env` | `FRIGATE_STREAM_TOKEN_*` |
| `host/frigate/config.yml` | go2rtc stream + camera block (idempotent) |
| `host/frigate/generated/` | copy of the fragment for review |

Then on Fedora:

```bash
sudo host/scripts/hash-mqtt-passwords.sh
# Install hashed passwords + acl to /etc/sentinel/mosquitto/, restart mosquitto
# Copy frigate config + env to /etc/sentinel/, restart frigate
```

## Human checklist (live bind)

1. Fresh flash → serial shows PoP; BLE scan shows `SENTINEL-XXXX`.
2. Run `sentinel-provision bind …` with matching `--ble-name` and `--pop`.
3. Command exits without error; camera gets static IP from CONTRACTS.
4. From the host: `curl -sS "http://10.77.0.11/stream?token=<token>"` returns MJPEG
   (token from `secrets/cameras/a.env` or `FRIGATE_STREAM_TOKEN_A`).
5. Reboot camera → **no** BLE advertise; stream still works.

Live BLE is not run in CI (`pytest` covers credentials and config edits only).

## Tests

```bash
cd host/provision && ../../.venv/bin/pytest -q
```
