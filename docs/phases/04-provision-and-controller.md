# Phase 4: Provisioning tool and controller

**Kind:** two separate coding agent prompts (fresh chats)  
**Model:** Composer 2.5 Fast (`composer-2.5-fast`) for both  
**Parent plan:** [../PLAN.md](../PLAN.md#phase-4-provisioning-tool-and-controller)

| Prompt | Wave | Depends on |
| --- | --- | --- |
| **A — controller** | **A** (with Phase 1 and 2) | CONTRACTS.md only; mock Frigate MQTT/HTTP |
| **B — provision CLI** | **B** (with Phase 3, after chip/sensor paste) | CONTRACTS.md bind payload; Phase 1 log optional |

Do **not** implement both prompts in one agent session unless the user explicitly
asks. Paste only the prompt section you want.

Contracts: [CONTRACTS.md](CONTRACTS.md). Frigate API:
`docs/vendor/frigate/docs/static/frigate-api.yaml` and `integrations/mqtt.md`.

---

## Prompt A — `sentinel-controller`

### Agent instructions

Implement the host controller only. Read CONTRACTS.md session state machine,
trigger rules, motion hold, evidence export, and config defaults. Do not build
BLE provisioning. Do not require a live Frigate or broker for unit tests.

### Goal

Python package `host/controller/` that:

1. Subscribes to `frigate/reviews` and `frigate/<cam>/motion` (and camera LWT /
   offline signals as specified in CONTRACTS / PLAN).
2. Runs IDLE → ARMED → COOLDOWN with no dead window on re-alert during COOLDOWN.
3. Publishes `sentinel/<id>/cmd` armed/idle to all cameras.
4. Creates/ends `sentinel_sync` manual events on the other cameras via Frigate HTTP.
5. Exports evidence to `evidence/<UTC timestamp>/` with `manifest.json` SHA-256.
6. Ships a Quadlet unit `host/quadlet/sentinel-controller.container` (or alongside
   Phase 2 units) and `host/controller/config.toml` defaults from CONTRACTS.

### Files

```text
host/controller/
  README.md
  pyproject.toml or requirements.txt
  Containerfile
  config.toml                 defaults from CONTRACTS
  src/…                       package
  tests/
    fixtures/                 recorded frigate/reviews JSON payloads
    test_state_machine.py
    test_evidence.py          fake Frigate HTTP (httpx mock / respx)
host/quadlet/
  sentinel-controller.container
```

### Test requirements

- pytest driven by fixture `frigate/reviews` payloads (new/update/end, severity,
  objects, sub_labels).
- Cases: person alert arms all; `ignore_sub_labels` skips; motion OFF + hold_seconds
  → cooldown; max_session_seconds cap; alert during COOLDOWN re-arms; offline camera
  triggers save on remaining.
- Evidence export tested against a fake HTTP API (no real Frigate).

### Out of scope

- Live BlueZ / `esp_prov`
- Editing Frigate config beyond documenting required MQTT users
- Push notifications (`notify` stays off)

### Verify

`pytest` green. Container builds if Podman/Docker available; otherwise Containerfile
reviewed for consistency with Phase 2 Quadlet patterns.

### Exit

Agent: tests green. Phase exit (with Prompt B + hardware): all three cameras bound;
triggering one produces saved exported alerts on all three; cameras switch armed/idle.

### Stop

Do not implement the provision CLI in this chat.

---

## Prompt B — `sentinel-provision` CLI

### Agent instructions

Implement the provisioning CLI only. Read CONTRACTS.md bind payload and camera
identity table. Wave B: human should have confirmed OV3660 / pinout via Phase 1 log.
Wrap vendored `esp_prov` patterns from
`docs/vendor/network_provisioning/network_provisioning/tool/esp_prov/`.
At runtime, use the copy installed by `scripts/install-esp-prov.sh`: source
`~/.config/jack-sentinel/env.sh` and run `$SENTINEL_ESP_PROV_DIR/esp_prov.py` with
`IDF_PATH=$SENTINEL_PROV_IDF_PATH`. Its Python deps (bleak, cryptography, protobuf)
are already in the repo `.venv`. Add `host/provision` with a `pyproject.toml` and
`scripts/setup-python-venv.sh` will install it editable.

### Goal

One command per camera that:

1. Generates per-camera MQTT username/password and stream token into `secrets/`.
2. Appends mosquitto ACL (and password file update instructions or hook) for that
   camera's topic tree.
3. Writes or patches go2rtc stream + Frigate camera block snippets (documented path
   under `host/frigate/`, idempotent includes or a generated fragment directory).
4. Sends Wi-Fi creds via standard provision + `sentinel-bind` custom payload over BLE.
5. Uses Security 2 with the device PoP the human provides (CLI flag / prompt).

### Files

```text
host/provision/
  README.md
  pyproject.toml or requirements.txt
  sentinel_provision/         package
  tests/
    test_credentials.py
    test_config_writes.py     temp dirs; no BlueZ
```

CLI name: `sentinel-provision` (console_script or `python -m`).

### Test requirements

- Unit-test credential generation and file edits without BlueZ.
- Golden/expected bind JSON shape matches CONTRACTS.md (no CA until Phase 6).
- Live BLE bind is **documented** as a human check, not required in CI.

### Out of scope

- Controller state machine (Prompt A)
- Flashing firmware
- Burning eFuses

### Verify

Unit tests green. README: example command line for `sentinel_a` with PoP, and the
human checklist (BLE visible → bind OK → stream URL works → reboot no advertise).

### Exit

Agent: tests + docs. Full phase exit shares Prompt A's hardware exit.

### Stop

Do not implement the controller in this chat. If BlueZ is missing on the agent host,
still ship the CLI; skip live scan.
