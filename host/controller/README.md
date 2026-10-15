# sentinel-controller

Host-side controller for the Sentinel desk cameras. It listens to Frigate MQTT
(`frigate/reviews`, `frigate/<camera>/motion`) and camera LWT
(`sentinel/<id>/state`), drives the IDLE → ARMED → COOLDOWN session machine from
[CONTRACTS.md](../../docs/phases/CONTRACTS.md), publishes `sentinel/<id>/cmd`, creates
`sentinel_sync` manual events on peer cameras, and exports evidence under
`evidence/<UTC timestamp>/`.

## Config

Defaults live in `config.toml`. Override paths and secrets with environment variables:

| Variable | Purpose |
| --- | --- |
| `SENTINEL_CONFIG` | Path to TOML (default `./config.toml`) |
| `SENTINEL_MQTT_PASSWORD` | MQTT password for the controller user |
| `SENTINEL_FRIGATE_API_KEY` | Frigate API bearer token if enabled |
| `SENTINEL_FRIGATE_URL` | Frigate base URL (default `http://127.0.0.1:5000`) |
| `SENTINEL_EVIDENCE_DIR` | Export root (default `/var/lib/sentinel/evidence`) |

## Development

```bash
cd host/controller
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Container

```bash
podman build -t localhost/sentinel-controller:latest -f Containerfile .
```

Quadlet unit: [../quadlet/sentinel-controller.container](../quadlet/sentinel-controller.container).

## MQTT subscriptions

- `frigate/reviews`
- `frigate/sentinel_{a,b,c}/motion`
- `sentinel/{a,b,c}/state` (LWT `offline`)

## Out of scope here

BLE provisioning (`sentinel-provision`), push notifications, and live Frigate in unit
tests.
