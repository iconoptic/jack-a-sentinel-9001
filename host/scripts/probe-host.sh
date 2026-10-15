#!/usr/bin/env bash
# Collect host facts for the Fedora runbook. Prints evidence. Does not decide
# whether the machine is suitable, and does not change system state.
set -uo pipefail

section() {
    printf '\n===== %s =====\n' "$1"
}

run() {
    section "$1"
    shift
    if "$@"; then
        return 0
    fi
    printf '(command failed: %s)\n' "$*"
    return 0
}

section "host"
date -Is
hostname
printf 'kernel: %s\n' "$(uname -r)"

run "lscpu" lscpu

if command -v lspci >/dev/null 2>&1; then
    section "lspci -k (network)"
    lspci -k | awk 'BEGIN{IGNORECASE=1} /network|ethernet|wireless|wi-fi/{c=4} c>0 {print; c--}'
else
    section "lspci -k (network)"
    printf 'lspci is not installed (Fedora package: pciutils)\n'
fi

if command -v iw >/dev/null 2>&1; then
    run "iw dev" iw dev
    section "iw list (interface modes and combinations)"
    # Keep only the mode list and the interface-combination block. Deeper-indented
    # lines belong to the section; the next sibling header ends it.
    iw list | awk '
        /^Wiphy / { wiphy = $0; next }
        /Supported interface modes:/ || /valid interface combinations:/ {
            print ""
            print wiphy
            print
            grabbing = 1
            header_indent = match($0, /[^[:space:]]/) - 1
            next
        }
        grabbing {
            if ($0 ~ /^[[:space:]]*$/) { grabbing = 0; next }
            this_indent = match($0, /[^[:space:]]/) - 1
            if (this_indent > header_indent) { print; next }
            grabbing = 0
        }
    '
    section "iw reg get"
    iw reg get || printf '(iw reg get failed)\n'
else
    section "iw"
    printf 'iw is not installed\n'
fi

run "ls -l /dev/dri" ls -l /dev/dri
run "ip -4 route" ip -4 route
run "ip -4 addr" ip -4 addr

section "how to read this"
cat <<'EOF'
This script only prints facts. It does not prove that an AP, VAAPI, OpenVINO,
or person detection works.

OpenVINO on the iGPU needs an Intel CPU of 6th generation (Skylake) or newer.
iw list must show "AP" under Supported interface modes, and a valid interface
combination that allows an AP while Ethernet stays the uplink.

If there is no AP mode, or the CPU is older than 6th gen, or you cannot tell
the generation from the model name: stop. Do not apply the rest of the runbook.
Use the host-probe escalation in docs/phases/README.md.

Paste this whole output into the Fedora notes. Do not commit it.
EOF
