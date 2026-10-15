#!/usr/bin/env bash
# Fallback if go2rtc leaves the literal {FRIGATE_STREAM_TOKEN_A} in the stream URL.
# Copies host/frigate/config.yml and substitutes only the stream token.
# MQTT placeholders stay; Frigate substitutes those itself (reference config).
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
src=$repo_root/host/frigate/config.yml
env_file=$repo_root/secrets/frigate.env
dest=/etc/sentinel/frigate/config.yml
force=0

if [[ "${1:-}" == "--force" ]]; then
    force=1
elif [[ -n "${1:-}" ]]; then
    printf 'Usage: %s [--force]\n' "$0" >&2
    exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
    printf 'Run as root: sudo %s [--force]\n' "$0" >&2
    exit 1
fi

[[ -f "$src" ]] || {
    printf 'Missing %s\n' "$src" >&2
    exit 1
}
[[ -f "$env_file" ]] || {
    printf 'Missing %s\n' "$env_file" >&2
    exit 1
}

if [[ -f "$dest" && "$force" -ne 1 ]]; then
    printf '%s exists. Re-run with --force to overwrite it.\n' "$dest" >&2
    exit 1
fi

python3 - "$src" "$env_file" "$dest" <<'PY'
import pathlib
import sys

src, env_path, dest = sys.argv[1:]
vals = {}
for raw in pathlib.Path(env_path).read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    vals[key] = value

token = vals.get("FRIGATE_STREAM_TOKEN_A", "")
if not token:
    sys.exit("FRIGATE_STREAM_TOKEN_A is empty")
if any(ch in token for ch in "#{}&\n\r \"'"):
    sys.exit("stream token has characters that would break the go2rtc URL")

text = pathlib.Path(src).read_text()
needle = "{FRIGATE_STREAM_TOKEN_A}"
if needle not in text:
    sys.exit(f"{needle} is not in {src}")
out = text.replace(needle, token)
path = pathlib.Path(dest)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(out)
path.chmod(0o640)
print(f"Wrote {dest} with the stream token substituted")
print("MQTT placeholders were left for Frigate. Restart frigate.service after this.")
PY
