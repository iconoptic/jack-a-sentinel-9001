# Phase 0: Ground rules

**Kind:** human checklist. Do not hand this to a coding agent.

**Parent plan:** [../PLAN.md](../PLAN.md#phase-0-ground-rules-before-mounting-anything)

## Goal

Finish workplace and placement rules before any camera is mounted or aimed at a
shared space.

## Checklist

- [x] Workplace sign-off: confirmed OK (2026-10-14).
- [ ] **Video only, no audio.** Audio recording brings in wiretap and consent laws in
      many US states. The OV3660 boards have no mic; keep it that way. Do not add a
      microphone in later phases.
- [ ] Aim the cameras at your own space, not at neighbors' desks or walkways.
- [ ] Consider a visible "this desk is on camera" sign. Deterrence may fix the problem
      before you need evidence.

## Contracts that already encode this

- [CONTRACTS.md](CONTRACTS.md) lists audio as never in scope.
- Face recognition default: enroll only yourself (`ignore_sub_labels`); leave
  coworkers unenrolled. See [../PLAN.md](../PLAN.md#6-faces-detection-vs-recognition).

## Exit

All boxes above are checked (sign-off already is). Then start Wave A:
[01-bench-bringup.md](01-bench-bringup.md), [02-host-mvp.md](02-host-mvp.md), and
Prompt A in [04-provision-and-controller.md](04-provision-and-controller.md).
