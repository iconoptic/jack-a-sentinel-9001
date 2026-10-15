# Review handoff: audit the implementation, write correction plans

**You are a fresh reviewer agent.** Paste this whole file as your first message, with
the repo root as your working directory. You do **not** fix the code. You audit what
exists, then write correction plans that other agents (Composer or Grok) will
execute in separate fresh chats.

Do not trust any "done", "verified" or "tests green" claim in this repo's docs,
READMEs or earlier chat summaries. Reproduce it yourself, or mark it **unverified**.

## 1. What this project is

Three ESP32-S3-CAM boards (OV3660 sensor, N16R8 module) watch one cubicle, and an
always-on Fedora box records. The owner, who is the user and uses they/them pronouns,
wants clear footage of whoever tampers with their desk, without hours of empty-desk
video.

- Cameras pair **once over BLE**, accept the first host, then BLE shuts off. Video
  goes over **Wi-Fi** to a hidden-SSID access point on the Fedora box's built-in
  Wi-Fi. The box's uplink stays on Ethernet. The AP is isolated, with no NAT and no
  forwarding.
- The host runs **Frigate 0.18.1** in Podman (Quadlet), plus mosquitto and a small
  custom `sentinel-controller` (Python). A person on any camera arms all three,
  keeps pre-roll, and exports evidence.
- Read, in this order: [../../README.md](../../README.md), [../PLAN.md](../PLAN.md),
  [CONTRACTS.md](CONTRACTS.md) (frozen interfaces), [README.md](README.md) (phase
  index and model routing), then the phase briefs `01`–`06`, then
  [../hardware.md](../hardware.md).

**Decisions already made by the user. Do not re-litigate them:**

| Topic | Decision |
| --- | --- |
| Transport | BLE for provisioning only. Video over Wi-Fi. Bluetooth video was measured on paper and rejected. |
| Network | Ethernet is the host uplink. Built-in Intel Wi-Fi is the camera AP only (hidden SSID, static IPs, firewalld zone `sentinel` with target `DROP`). |
| Host | i7, Intel graphics, more than 500 GB. OpenVINO on the iGPU, VAAPI for decode. |
| Machines | **Arch** is the firmware dev and flash machine. **Fedora** is the host. |
| Evidence | Stays on the host. No off-box copy. |
| Notifications | None for now. Events go to the Frigate review timeline. |
| Workplace | Sign-off confirmed OK. |
| Power | One 5 V supply with a custom three-drop wire harness. USB carries power only. |
| Faces | Trigger on `person`. Face detection and recognition only add a label. **Enroll only the owner.** Video only, **no audio**. |

## 2. Repo snapshot (checked at handoff time, 2026-10-14)

Verified by the previous agent:

- `git init` was run but there are **no commits**. Everything is untracked.
- `scripts/` (install-arch, install-fedora, install-esp-idf, install-esp-prov,
  setup-python-venv, idf-env, fetch-docs, `lib/`): ShellCheck-clean. The venv and
  esp_prov installers were run in an isolated scratch copy and worked, and `esp_prov`
  loaded Security 2 and the BLE transport. **The `sudo pacman`/`dnf` steps and the
  Fedora readiness checks have never been run.** The Fedora package names were
  checked against Fedora 44 metadata only.
- ESP-IDF v6.0.3 is now installed on this Arch box (`~/esp/esp-idf-v6.0.3`,
  `~/.espressif`).
- `host/controller/`: 8 pytest tests pass. `host/provision/`: 6 pytest tests pass.

Observed just before handoff, and not yet investigated:

- `firmware/bringup/`: a build was attempted and **failed**. The log is
  `firmware/bringup/build/log/idf_py_stderr_output_436710`, with
  `Failed to resolve component 'esp32-camera' required by component 'main'`. There is
  no `managed_components/`, no `dependencies.lock` and no `.bin`. Find the root
  cause. It may be a missing component-manager step, a manifest problem, or a
  v6-specific dependency declaration.
- `firmware/sentinel/`: `managed_components/` is populated (esp32-camera, esp_jpeg,
  mqtt, network_provisioning, json_generator, cjson), but there is no `sdkconfig` and
  **no built binary**. It has never compiled. `host_test/` has never run.

Everything else, meaning all firmware logic, the Frigate config, the Quadlet units,
`setup-ap.sh`, the firewalld zone, the mosquitto config and the provisioning CLI's BLE
path, is **unverified against real hardware**. No board has been flashed. The Fedora
box has not been touched.

## 3. Your job

1. **Establish ground truth.** Build, test and lint everything you can on this Arch
   machine, and record exact commands and results. Section 6 lists the commands.
2. **Review against the contracts.** Check every implemented piece against
   [CONTRACTS.md](CONTRACTS.md), its phase brief and [../PLAN.md](../PLAN.md). Report
   drift in either direction: code that deviates from the contract, and a contract
   that is wrong or underspecified.
3. **Write correction plans** (Section 7) that a fresh Composer or Grok agent can
   execute without reading this chat.

### Review dimensions

Be specific. Cite `path:line`. For each defect, say what breaks and how you know.

1. **Does it build and run at all?** Fix-first blockers: the bringup build failure,
   the sentinel first compile, ESP-IDF v6 API changes (`esp_mqtt`, `esp_http_server`,
   `network_provisioning` naming and manager API, BT memory release calls, NVS
   security APIs). Check the code against the vendored v6.0.3 docs and headers, not
   against memory of v5.
2. **Bind and pairing correctness** (the core requirement: first host wins, then BLE
   stays off):
   - State machine: crash or power loss between "Wi-Fi creds written" and
     `bound=1`, partial binds, a second host attempting to bind a BOUND device, BOOT
     reset during bind.
   - Is BLE really never started when BOUND? Is controller memory released?
   - How is the proof-of-possession generated and shown? Is it unique per device and
     out of git?
3. **Secrets at rest on the camera.** The plan says "encrypted NVS". Without flash
   encryption, an `nvs_keys` partition sits in plaintext flash beside the data, which
   protects little. Check what was implemented and whether the docs and README
   oversell it. Do not recommend burning eFuses. That is a Grok escalation after OTA
   works and needs a human.
4. **Stream and HTTP security.** The stream token travels in a `?token=` query
   string. Check log leakage (camera, go2rtc, Frigate), constant-time comparison,
   and behavior with a missing or short token. Check single-client handling and what
   happens when go2rtc reconnects.
5. **MQTT and command handling.** LWT and retained state, topic ACLs matching
   [CONTRACTS.md](CONTRACTS.md), `armed` TTL fallback to `idle`, malformed JSON
   handling, the telemetry fields, and reconnect backoff.
6. **Camera robustness.** Watchdogs, Wi-Fi backoff, pinned BSSID and channel
   (hidden SSID, no probing for other networks), frame-buffer ownership and leaks,
   PSRAM settings (octal), brownout detector, and the fixed HD resolution default.
7. **Controller logic.** The cross-camera state machine: all transitions in
   [../PLAN.md](../PLAN.md) section 5. Re-arm during COOLDOWN, `max_session_seconds`,
   `hold_seconds` driven by motion across all cameras, manual events created with a
   `null` duration actually being ended (leak on crash or restart), idempotency, a
   duplicate `frigate/reviews` message, `ignore_sub_labels`, Frigate API auth, evidence
   export plus SHA-256 manifest, and that exported evidence is outside Frigate's
   retention.
8. **Provisioning CLI.** The BLE path against the vendored `esp_prov` tool, the
   Security 2 usage, the shape of the bind JSON versus CONTRACTS, credential generation
   quality, **file permissions on generated secrets**, idempotent config writes, and
   that nothing secret is printed to logs or written into git-tracked paths.
9. **Host configuration validity.** `host/frigate/config.yml` keys against the
   vendored Frigate 0.18.1 docs (`docs/vendor/frigate/`) and
   `docs/vendor/frigate/docs/static/frigate-api.yaml`. Check the go2rtc stream
   syntax with `?token=` and `#video=h264#hardware`, `motion.mqtt_off_delay`, the
   OpenVINO detector, `record.*` keys, and the review `labels`. Check the Quadlet units
   for the SELinux `:Z` labels, `/dev/dri` passthrough, shm size, image digests rather
   than floating tags, restart policy and ordering. Check `host/network/setup-ap.sh`
   and `sentinel-zone.xml`: hidden SSID, `ipv4.method manual`, `never-default`, no
   forwarding, and that the zone allows only MQTT (and later OTA HTTPS).
10. **Scripts.** Read `scripts/` critically, since you cannot run the `sudo` steps.
    Look for non-idempotent steps, anything that could clobber the user's setup
    (for example the Fedora script offering to disable system `mosquitto`, enabling
    `firewalld`, and the pyenv-versus-system Python pinning for ESP-IDF), partial-failure
    behavior, and Fedora or Arch differences I may have missed.
11. **Repo hygiene.** `.gitignore` covers build output, `sdkconfig`, `secrets/`,
    `wifi.local`, footage and caches. Build artifacts such as `firmware/*/build/` and
    `managed_components/` are present in the tree, so confirm they are ignored. Confirm
    **no secrets** are committed or committable (PoP codes, PSKs, tokens, passwords, PEMs).
12. **Guardrails.** Confirm that nothing records audio, nothing enrolls anyone but the
    owner, nothing phones home, and nothing in the repo burns eFuses or runs `espefuse`.
13. **Docs versus reality.** Numbers in the PLAN and `hardware.md` that are estimates
    but read as measurements (BLE throughput, fps, JPEG sizes, current draw, voltage
    drop). Phase briefs that now contradict each other or CONTRACTS. Dead links and
    renamed doc paths (ESP-IDF v6 moved its Linux setup page).

## 4. Rules

- **Read-only on implementation code.** Do not edit anything under `firmware/`,
  `host/` or `scripts/`. You may create files under `docs/review/` only. Stop and say
  so if you think a change is too small to plan.
- **No `sudo`, no package installs, no hardware access.** No SSH to the Fedora box
  unless the user gives access in this chat. If the Arch box has a board plugged in,
  do not flash it. Report only what `ls /dev/ttyUSB* /dev/ttyACM*` shows.
- **Never run** `espefuse`, `idf.py efuse*`, `idf.py encrypted-flash` or anything that
  burns fuses.
- **No commits, no pushes.** The user will commit.
- Do not print or copy secret values into your reports. Refer to them by file and
  field name.
- Build in a **copy** if a build would pollute the tree beyond the existing ignored
  `build/` dirs. The scratchpad directory is available for temp files.
- Distinguish **verified** (you ran it and saw the result), **inferred** (read the
  code and reasoned), and **unverified** (could not check, and why).
- Do not expand scope into new features. Features that are missing but listed in a
  brief are findings. Features nobody asked for are not.

## 5. Model routing for the correction plans

Follow [README.md](README.md). Composer 2.5 Fast (`composer-2.5-fast`) gets
well-specified, contract-determined, mechanical work. Grok 4.7
(`grok-4.7-xhigh-fast`) gets the judgement calls.

| Give to **Composer** | Give to **Grok** |
| --- | --- |
| Build and dependency fixes with an exact error | Anything where the contract is silent or wrong and a design decision is needed |
| API-rename and ESP-IDF v6 migration fixes | Security design (NVS protection strategy, token handling, bind-race handling) |
| Contract drift with an unambiguous correct side | Controller state-machine corrections that change behavior |
| Missing tests with the expected behavior stated | Resolution or thermal escalation if HD fails measurement |
| Config key fixes verified against vendored docs | The eFuse and Secure Boot procedure (writing it only; a human runs it) |
| Script and doc corrections | Resolving conflicts between PLAN, CONTRACTS and the briefs |

If you are unsure, say which model and why, and what evidence would change the
choice. A plan that needs a human action (flashing, Fedora access, measuring) says so
in a **Human gate** line and does not hand that step to an agent.

## 6. Ground-truth commands (run these first and record the output)

```sh
# Environment
. scripts/idf-env.sh && idf.py --version
git status --short | head

# Controller and provisioning tests
(cd host/controller && ../../.venv/bin/python -m pytest -q)
(cd host/provision  && ../../.venv/bin/python -m pytest -q)

# Shell scripts
python3 -m venv "$SCRATCH/sc" && "$SCRATCH/sc/bin/pip" install -q shellcheck-py
"$SCRATCH/sc/bin/shellcheck" -x -P SCRIPTDIR scripts/*.sh scripts/lib/*.sh host/scripts/*.sh host/network/*.sh

# Firmware: copy first so the repo tree stays clean
cp -r firmware/bringup  "$SCRATCH/bringup"  && (cd "$SCRATCH/bringup"  && idf.py set-target esp32s3 && idf.py build)
cp -r firmware/sentinel "$SCRATCH/sentinel" && (cd "$SCRATCH/sentinel" && idf.py set-target esp32s3 && idf.py build)

# Firmware host tests (Linux target), see firmware/sentinel/README.md and host_test/
# YAML / unit syntax
python3 -c "import yaml,sys; yaml.safe_load(open('host/frigate/config.yml'))"
systemd-analyze verify host/quadlet/*.container 2>&1 | head   # may need quadlet-generator; note if unavailable
```

`$SCRATCH` is the scratchpad directory from your environment. Some of the build
commands may need network access for the component manager. If a command fails for
environmental reasons, record that and move on. A fix-the-environment item is itself a
finding.

## 7. Deliverables (all under `docs/review/`)

1. **`REVIEW-REPORT.md`**
   - Scope and method: what you ran, what you read, what you could not check.
   - Ground-truth table: each command, its result, and verified/unverified.
   - Findings table, sorted by severity (**Blocker** = does not build or run, or
     breaks a stated requirement or a security guarantee; **High**; **Medium**;
     **Low**; **Nit**). Each finding has: id (`F-001`…), severity, dimension, file and
     line, what is wrong, how you know (verified, inferred or unverified), and the fix
     plan that owns it.
   - A short "what looks solid" section, so the next agent doesn't redo good work.
   - A summary of anything that needs a human decision from the user.
2. **One correction plan per workstream**, named `FIX-NN-<slug>.md`, written as a
   **self-contained prompt for a fresh agent**. Each contains:
   - **Assigned model** and one line of justification.
   - **Context**: the minimum a stranger needs, with links to CONTRACTS and the exact
     files. No references to "earlier discussion".
   - **Findings covered** by id, each with the file and line and the expected
     behavior.
   - **Tasks**: ordered, small, each with a concrete acceptance check.
   - **Files allowed to change** and **files that must not change**. A plan that
     must change CONTRACTS.md says so explicitly and says exactly what to change.
   - **Verify**: the exact commands that prove the fix.
   - **Out of scope** and **Stop conditions**.
   - **Human gate** lines for anything an agent must not do.
3. **`FIX-ORDER.md`**
   - The dependency graph between the plans, what can run in parallel, and which
     blocker unlocks which.
   - The launch paste for each plan, in the style of [README.md](README.md).
   - What to re-run after all plans are done (the Section 6 commands).

Suggested workstreams (adjust to what you find, merge or split as needed):
build and dependency blockers; ESP-IDF v6 migration; bind and security; stream, MQTT
and camera robustness; controller; provisioning CLI; host config and Quadlet; scripts;
docs and contract drift.

## 8. Done when

- Every Blocker and High finding is owned by a plan.
- Every plan can be pasted into a fresh chat and executed without this one.
- You have listed, honestly, what you did not verify.
- You stop. Do not start executing the plans.

Final message to the user: a short summary of the findings by severity, the list of
plans with their assigned model, anything needing the user's decision, and the one
thing they should do first.
