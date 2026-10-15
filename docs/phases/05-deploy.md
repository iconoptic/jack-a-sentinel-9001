# Phase 5: Deploy in the cubicle

**Kind:** human checklist. Do not hand mask polygons or mount angles to a coding agent.

**Model for optional follow-up:** Grok 4.7 only if a week of footage does not make
threshold / `hold_seconds` choices obvious (short notes review, not a new phase).

**Parent plan:** [../PLAN.md](../PLAN.md#phase-5-deploy-in-the-cubicle)

## Prerequisites

- [ ] Phase 2 exit on Fedora: person alert with ~10 s pre-roll on at least one camera.
- [ ] Phase 3 exit: bind, stream, no BLE after reboot, BOOT-hold reset works.
- [ ] Phase 4 exit: all three cameras bound; cross-camera armed + evidence export works
      on the bench or temporary placement.
- [ ] Phase 0 aiming rules still respected (own desk only, video only).

## Checklist

- [ ] Mount the cameras: desk surface + approach, overlapping fields of view so one
      covered camera does not blind the system.
- [ ] Build the power harness ([../hardware.md](../hardware.md#power)): one 5 V
      supply, trunk of 18–20 AWG, bulk capacitor at each camera. Out of easy reach;
      tidy, tamper-evident placement. USB carries power only; Wi-Fi carries video.
- [ ] Draw Frigate motion masks over monitors and windows (in the Frigate UI). Do not
      ask an agent to invent polygon coordinates without screenshots of the live view.
- [ ] Run for **one week**, then tune `hold_seconds`, detection thresholds, and
      retention using real false-positive / miss notes.
- [ ] Confirm offline/tamper path: covering or unplugging one camera still saves the
      others and appears on the review timeline.
- [ ] Confirm evidence directories land under `evidence/` with valid `manifest.json`
      hashes.

## Optional Grok pass

If after the week it is unclear whether to raise thresholds or change `hold_seconds`,
paste: false-positive count, miss notes, current config.toml, and a short description
of the desk layout. Ask Grok to recommend numeric changes only—no new architecture.

## Exit

System runs in the cubicle for a week with acceptable false positives and reliable
cross-camera saves. Then proceed to [06-hardening.md](06-hardening.md).

## Out of scope for any coding agent in this phase

- Guessing motion mask polygons
- Changing CONTRACTS.md identities or MQTT schemas
- Flash encryption / Secure Boot
