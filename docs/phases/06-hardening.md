# Phase 6: Hardening

**Parent plan:** [../PLAN.md](../PLAN.md#phase-6-hardening)

Two prompts. Use separate fresh chats. **Composer never burns eFuses.**

| Prompt | Model | When |
| --- | --- | --- |
| **A — OTA + MQTT TLS** | Composer 2.5 Fast | After Phase 5 week |
| **B — Flash encryption / Secure Boot** | Grok 4.7 (`grok-4.7-xhigh-fast`) | After OTA works; before any `espefuse` |

Contracts: extend bind payload with `mqtt_ca_pem` and port `8883` as already reserved
in [CONTRACTS.md](CONTRACTS.md). Update CONTRACTS.md and provision CLI when TLS lands.

Fedora LUKS on the recordings disk and disabling auto-login are **runbook steps on
the host**, not commands the agent runs from this Arch checkout unless the user
explicitly provides Fedora access.

---

## Prompt A — OTA and MQTT TLS (Composer)

### Agent instructions

Implement signed OTA from the host and MQTT over TLS. Read CONTRACTS.md Phase 6
notes and vendored ESP-IDF OTA / `esp_https_ota` docs plus mosquitto TLS docs.
Do **not** run `espefuse` or enable flash encryption / Secure Boot in this prompt.

### Goal

1. **OTA:** cameras pull signed firmware images over HTTPS from the host (port
   allowed in the `sentinel` firewall zone). Document image build, signing, and
   publish layout under `host/` (e.g. static file service or dedicated Quadlet).
2. **MQTT TLS:** host CA; deliver CA PEM in bind payload field `mqtt_ca_pem`;
   broker on `8883`; update mosquitto config, firewall, firmware MQTT client, and
   `sentinel-provision` bind JSON.
3. **Runbook:** Fedora LUKS for recordings volume; disable auto-login—checklist
   only, with links to Fedora docs; do not destructive-repartition anything without
   explicit user approval in the chat.

### Verify

- Unit/integration tests where practical (TLS config generation, bind payload with CA).
- Document human test: OTA one bench camera, then MQTT TLS reconnect.
- Refuse any request in this chat to burn eFuses; point to Prompt B.

### Stop

Do not implement Secure Boot / flash encryption here.

---

## Prompt B — Flash encryption and Secure Boot v2 (Grok)

### Agent instructions

You are writing the irreversible eFuse procedure for **one** development board first.
Read `docs/vendor/esp-idf/docs/en/security/` (after fetch-docs) and CONTRACTS /
PLAN warnings.

**Hard rules:**

1. Do **not** run `espefuse`, `idf.py efuse`, or any command that burns fuses.
2. Output a step-by-step document the human will run, with checkboxes.
3. **Development mode on one board first**, verify OTA + boot + bind secrets still
   work, then a separate release-mode section.
4. Call out what becomes unrecoverable (readback of flash keys, unsigned app reject).
5. Stop and wait for explicit human confirmation between development-mode steps and
   any release-mode steps.
6. Prefer committing a new doc such as `docs/phases/06-efuse-runbook.md` or
   `firmware/sentinel/docs/SECURE_BOOT.md` rather than editing random files.

### Goal

A runbook the human can follow to enable flash encryption + Secure Boot v2 without
bricking all three boards on the first try.

### Stop

End the chat when the runbook is written and the human has been told to run it
themselves. Do not execute fuse burns even if the user pastes "just do it" without
confirming they have a disposable board and a recovery plan.

---

## Phase exit

- OTA works for mounted cameras without USB.
- MQTT is TLS with per-camera creds still ACL-scoped.
- At least one board has completed **development-mode** secure boot/flash-encrypt
  validation before any release-mode burns on the fleet.
- Recordings volume encrypted at rest (LUKS); host auto-login off.
