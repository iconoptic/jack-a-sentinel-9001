# Sync the deployment PC: local fixes + latest repo

**Kind:** one coding agent prompt, run **on the deployment PC** (the always-on host in the
cubicle), in that machine's clone of this repo  
**Model:** Composer 2.5 Fast (`composer-2.5-fast`). Escalate only step 6's firmware
conflicts to Grok 4.7 (`grok-4.7-xhigh-fast`) if they are not mechanical.  
**Human:** stays nearby. The agent stops at the three **CHECKPOINT** lines below.

Paste this whole file as the first message of a fresh chat.

---

## Situation

The repo on this PC was cloned earlier and then changed locally, with another AI's help, until
the camera network worked. None of it was committed or pushed. Meanwhile the remote
`origin/main` moved on. Known local changes:

- **Wi-Fi card and networking fixes.** Likely in `host/network/` (`install-ap.sh`,
  `setup-ap.sh`, `sentinel-zone.xml`), and quite possibly **outside the repo**: NetworkManager
  settings, `/etc/modprobe.d/` driver options, firewalld, rfkill, systemd units edited in place.
- **Camera selection**: installing and running only some cameras (one camera, `sentinel_a`, is
  deployed).
- **Firmware changes** that may fix ffmpeg input-format errors. Not flashed yet.

The remote probably contains: `--cameras` support in the installers (it may duplicate the
local camera selection), Arch/Fedora detection in `host/network/install-ap.sh` (it will likely
**conflict** with the local Wi-Fi fixes in the same file), and Phase 7 "simple mode"
(`host/recorder/`, `install-services.sh --mode`), see [07-simple-motion-mode.md](07-simple-motion-mode.md).

**Goal:** a branch on the remote holding the latest remote code **plus** every local change that
was needed to make the hardware work, written in the repo's conventions, with nothing lost and
no secret committed.

## Hard rules

1. **Never** run: `git reset --hard`, `git clean` (any flags), `git checkout -- .`,
   `git restore .`, `git stash drop`/`clear` before step 9, `git stash -a`/`--all`,
   `git push --force`, or a push to `main`.
2. **Never** read out, print, paste, or commit anything under `secrets/`, any `*.env`, PSK, MQTT
   password or stream token. `secrets/` is gitignored; `git stash -u` does not touch it. Keep it that way.
3. Do **not** restart services, run the installers, change NetworkManager/firewalld, or flash a
   camera. The camera is deployed and recording; this task only changes the repo. Read-only
   commands under `sudo` (listing, `cat` of non-secret config) are fine.
4. Redact before writing notes: replace SSIDs, PSKs, tokens, passwords and MACs with `<redacted>`.
5. When a rule here and your judgement disagree, stop and ask.

Work in the repo root. Set once:

```sh
TS=$(date +%Y%m%d-%H%M%S)
BK=~/sentinel-sync-backup/$TS
mkdir -p "$BK" && chmod 700 "$BK" && echo "$TS" > ~/sentinel-sync-backup/CURRENT
```

Agent shells may not keep variables between commands. Start every later command with:

```sh
TS=$(cat ~/sentinel-sync-backup/CURRENT); BK=~/sentinel-sync-backup/$TS; STASH=$(cat "$BK/stash.sha" 2>/dev/null)
```

---

## Step 1 — Record where everything is (read-only)

```sh
git status --short --branch        > "$BK/status.txt"
git rev-parse HEAD                 > "$BK/head.txt"
git remote -v                      > "$BK/remotes.txt"
git stash list                     > "$BK/stash-list-before.txt"
git log --oneline origin/main..HEAD > "$BK/local-commits.txt"   # before any fetch: commits never pushed
```

- If `local-commits.txt` is not empty, there are local commits that were never pushed. Note
  them; step 5 handles them.
- If `stash-list-before.txt` is not empty, there are older stashes. Do not touch them. Our stash
  gets a unique message so it can be told apart.

## Step 2 — Back up before anything moves

```sh
git diff --binary HEAD             > "$BK/local-tracked.patch"
git ls-files -o --exclude-standard -z > "$BK/untracked.list0"
tar --null -T "$BK/untracked.list0" -czf "$BK/local-untracked.tgz"
git branch "backup/deploy-pc-$TS" HEAD
cp -a secrets "$BK/secrets" && chmod -R go-rwx "$BK/secrets"
```

If that `cp` hits permission errors (the installers run some steps as root), use
`sudo cp -a secrets "$BK/secrets" && sudo chown -R "$USER": "$BK/secrets"` instead. Do not open the copies.

Check: `tar -tzf "$BK/local-untracked.tgz" | wc -l` equals the number of entries in the list, and
`local-tracked.patch` is non-empty if `git status` showed modified files. Stop if not.

## Step 3 — Find the changes made outside the repo (read-only)

The hardware fixes may live in system files, not in the repo. If they are not captured, the next
install or reinstall loses them. Collect, **redacted**, into `$BK/out-of-repo.md`:

```sh
# Files changed in the last 30 days in the places Wi-Fi/AP fixes usually land
sudo find /etc/NetworkManager /etc/modprobe.d /etc/modules-load.d /etc/udev/rules.d \
  /etc/firewalld /etc/systemd/system /etc/sysctl.d /etc/sentinel /etc/containers/systemd \
  -type f -mtime -30 -printf '%TY-%Tm-%Td %TH:%TM  %p\n' 2>/dev/null | sort

# Shell history mentions of network / driver / service commands
grep -nE 'nmcli|iw |iwconfig|rfkill|modprobe|iwlwifi|firewall-cmd|systemctl|podman|esptool|idf\.py' \
  ~/.bash_history ~/.zsh_history 2>/dev/null | tail -n 200

# Current state to compare with what the repo's scripts would create
nmcli -f NAME,TYPE,DEVICE,AUTOCONNECT connection show
nmcli connection show sentinel-ap | grep -viE 'psk|password|ssid|mac|bssid'
iw dev
sudo firewall-cmd --info-zone=sentinel
cat /etc/modprobe.d/*.conf 2>/dev/null
ls -l /etc/NetworkManager/conf.d/ /etc/NetworkManager/dispatcher.d/ 2>/dev/null
```

For each file under `/etc/sentinel` and `/etc/containers/systemd`, compare with the repo's
source of it (`host/quadlet/*`, `host/mosquitto/mosquitto.conf`, `host/frigate/config.yml`). A file
edited in place under `/etc` will be **overwritten** by the next `install-services.sh` run, so
any meaningful difference is a local fix that must move into the repo. Do not `cat` files that
hold secrets (`/etc/sentinel/*.env`, `mosquitto/passwords`, NetworkManager `system-connections/`).
List their names only.

Also ask the human once: "Do you have the chat transcript or a summary from the AI that fixed the
Wi-Fi? Paste it if so." Use it as a hint, not as truth; the files are the truth.

## Step 4 — Review the remote before merging (read-only)

```sh
git fetch origin
git log --oneline HEAD..origin/main                      > "$BK/remote-commits.txt"
git diff --stat HEAD origin/main                          > "$BK/remote-diffstat.txt"
git diff --name-only HEAD                | sort > "$BK/local-files.txt"
git diff --name-only HEAD origin/main    | sort > "$BK/remote-files.txt"
comm -12 "$BK/local-files.txt" "$BK/remote-files.txt"   > "$BK/both-changed.txt"
# Untracked local files that the remote now tracks: these block `git pull` and collide on unstash
tr '\0' '\n' < "$BK/untracked.list0" | sort | comm -12 - "$BK/remote-files.txt" > "$BK/untracked-collisions.txt"
```

Read the remote diff for every file in `both-changed.txt` and `untracked-collisions.txt`
(`git diff HEAD origin/main -- <file>`) next to the local diff (`git diff HEAD -- <file>`).

Now write **`docs/deploy-notes/SYNC-<YYYY-MM-DD>.md`** (create `docs/deploy-notes/`). One row per
local change, both in-repo and out-of-repo (step 3):

| Change | Where | Class | Plan |
| --- | --- | --- | --- |
| e.g. AP uses `iw` to set the regulatory domain before bringing up the hotspot | `host/network/setup-ap.sh` | **keep** | port into the remote's version of the script |

Classes:

- **already-upstream**: the remote already does the same thing (e.g. camera selection via
  `--cameras`). Plan: take the remote's version, drop the local one. Note any behaviour the local
  version had that the remote lacks; that part becomes **keep**.
- **keep**: a hardware-proven fix the remote lacks. Plan: port it, in the repo's style.
- **cruft**: debugging leftovers (extra `echo`, `set -x`, hardcoded test IPs, commented blocks,
  temporary files). Plan: drop.
- **decide**: a local change that contradicts a design decision in `docs/PLAN.md`,
  `CONTRACTS.md`, or the remote code (e.g. DHCP on the AP, a different subnet, a changed
  `/stream` format, BLE behaviour, a hardcoded credential). Plan: none until the human says.

**CHECKPOINT 1.** Show the human the table. Ask only about **decide** rows and anything in
`local-commits.txt`. Wait for answers. Record them in the notes file.

## Step 5 — Stash, pull

```sh
git stash push -u -m "deploy-pc-local-$TS"
git rev-parse 'stash@{0}' > "$BK/stash.sha"   # refer to the stash by this SHA from now on
git stash list | head -n 3                    # stash@{0} message is deploy-pc-local-$TS
git status --short                            # must be clean except ignored files
```

- **No local commits** (`local-commits.txt` empty): `git pull --ff-only origin main`.
- **Local commits exist**: `git pull --rebase origin main`. Resolve conflicts with the step 4
  plan. If a conflict is not covered by the plan, `git rebase --abort` and stop for the human.
  `backup/deploy-pc-$TS` still has the original commits.

## Step 6 — Unstash and integrate

Use `apply`, not `pop`, so the stash survives until the end:

```sh
git stash apply "$STASH"
```

If it fails with `<path> already exists, no checkout` / `could not restore untracked files from
stash` (the remote now tracks a file that was untracked here), do **not** run `apply` again:

1. `git diff --stat`. Recent git (2.4x+) has already applied the tracked changes before it
   failed on the untracked ones. Only if they are missing:
   `git diff "$STASH^1" "$STASH" --binary > "$BK/tracked-only.patch" && git apply --3way "$BK/tracked-only.patch"`
2. None of the stash's untracked files were restored. List them with modes:
   `git ls-tree -r "$STASH^3"`. For each one:
   - not present in the tree now: `git show "$STASH^3:<path>" > "<path>"`
   - now tracked by the remote: `git show "$STASH^3:<path>" > "<path>.local"`, then merge the two by hand
   - mode `100755`: `chmod +x` the restored file
3. Compare against `$BK/untracked.list0` so nothing is missed.

Resolve every conflict, and handle every notes-table row, with these rules:

| Area | Rule |
| --- | --- |
| `host/network/*` (Wi-Fi/AP) | Start from the remote file. Add the local fixes the notes mark **keep**, preserving the remote's Arch/Fedora detection, `confirm` prompts and idempotency. A fix that existed only as a system change (step 3) becomes code: e.g. a `host/network/*.conf` the installer copies into `/etc/modprobe.d/`, or an `nmcli` property in `setup-ap.sh`, with a comment saying which card or symptom it fixes. |
| Camera selection | One mechanism: the remote's `--cameras` flags (`install-fedora.sh`, `install-services.sh`, `generate-secrets.sh`, `render-frigate`, `render-recorder` if present). Port any extra local behaviour onto those flags. Delete the duplicate local mechanism. |
| `firmware/` | Keep local changes only if `/stream` and `/snapshot` still match `CONTRACTS.md` (multipart JPEG, bearer or `?token=`) and MQTT topics are unchanged. A changed frame size, JPEG quality or boundary is allowed if the notes say why; record it in `CONTRACTS.md` "Stream resolution". Anything else is **decide**. Never commit `sdkconfig`, `wifi.local`, or a hardcoded SSID/PSK/token. |
| `/etc` edits to Frigate, mosquitto, Quadlet units | Move the meaningful difference into `host/frigate/config.yml` or `host/provision/sentinel_provision/frigate_config.py` (the installer renders from these), `host/mosquitto/`, or `host/quadlet/`. |
| Simple mode (`host/recorder/`, `--mode`) | Remote wins. Local changes do not touch it. |
| Docs | If a local fix changes how setup works, update `host/RUNBOOK.md` and `host/network/README.md` in the same commit. |

Delete any `<path>.local` helper files once merged.

## Step 7 — Verify (no services touched)

Stage everything first, so files restored from the stash are included, and read the list:

```sh
git add -A && git status --short          # no secrets/, *.env, *.local, build/, sdkconfig in this list
git diff --cached --check
changed_sh=$(git diff --cached --name-only origin/main | grep -E '\.sh$' || true)
[ -n "$changed_sh" ] && shellcheck $changed_sh
for f in $changed_sh; do bash -n "$f" || echo "SYNTAX $f"; done
scripts/setup-python-venv.sh              # repo .venv with controller/provision/recorder [dev]
for d in host/controller host/provision host/recorder; do
  [ -d "$d" ] && (cd "$d" && ../../.venv/bin/python -m pytest -q)
done
```

Every pytest run must pass. A failure in a file the merge touched is yours to fix; a failure in
a file nobody touched goes in the report, unfixed.

If ESP-IDF is installed here (`. scripts/idf-env.sh` works) and `firmware/` changed:
`idf.py -C firmware/sentinel build`. Do not flash.

**Secret scan of the result.** This prints only file names and the secret's key name, never a value:

```sh
python3 - <<'PY'
import pathlib, re, subprocess
SECRET_KEY = re.compile(r"SSID|PSK|PASSWORD|TOKEN|BSSID")
vals = {}
for f in pathlib.Path("secrets").rglob("*"):
    if not f.is_file():
        continue
    try:
        text = f.read_text()
    except UnicodeDecodeError:
        continue
    if f.name.endswith(".password"):
        vals[str(f)] = text.strip()
    for line in text.splitlines():
        line = line.strip()
        if f.name == "users" and ":" in line:
            user, v = line.split(":", 1)
            vals[f"{f}:{user}"] = v
        elif "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            if SECRET_KEY.search(k):
                vals[f"{f}:{k}"] = v.strip().strip("\"'")
vals = {k: v for k, v in vals.items() if len(v) >= 6}
files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"],
                       capture_output=True, text=True, check=True).stdout.split("\0")
hits = 0
for path in filter(None, files):
    try:
        body = pathlib.Path(path).read_text(errors="ignore")
    except (IsADirectoryError, FileNotFoundError):
        continue
    for name, v in vals.items():
        if v in body:
            print(f"SECRET {name} appears in {path}")
            hits += 1
print(f"checked {len(vals)} secret values; secret scan:", "CLEAN" if hits == 0 else f"{hits} HIT(S)")
PY
```

It checks tracked and new (not ignored) files. Expect roughly 15–20 values checked; `0` means
`secrets/` is missing or unreadable, so stop. Any hit: remove it from the file and stop for the human.
Run it again just before the push in step 8.

**CHECKPOINT 2.** Show the human `git status`, `git diff --stat origin/main`, the test results and
the scan result.

## Step 8 — Commit on a branch and push it

```sh
git switch -c "sync/deploy-pc-$TS"
```

Unstage with `git reset -q` (plain `reset` only touches the index; never `--hard`), then `git add`
the files for one commit at a time. Commit in small logical pieces, conventional style like the existing history
(`fix(network): …`, `feat(host): …`, `docs: …`), e.g. network fixes, camera selection, firmware,
deploy notes. Include `docs/deploy-notes/SYNC-<date>.md` (redacted). Then:

**CHECKPOINT 3.** Ask the human: "Push `sync/deploy-pc-$TS` to origin?" On yes:

```sh
git push -u origin "sync/deploy-pc-$TS"
```

Do not merge to `main`. The human reviews and merges (from any machine).

## Step 9 — Clean up and hand back

- Only after the push succeeded, drop our stash by its index (never by guessing `stash@{0}`):
  `git stash drop "$(git stash list --format='%gd %H' | awk -v s="$STASH" '$2==s{print $1}')"`
- Keep `$BK` and the `backup/deploy-pc-$TS` branch. Tell the human where they are and that they can
  delete them after the merge has run on real hardware for a few days.
- Report: what was kept, what was dropped as already-upstream or cruft, the **decide** answers, and the
  next human steps:
  1. Merge the branch, `git switch main && git pull` here.
  2. Flash the camera with the newest firmware if it changed: `scripts/install-esp32.sh a`.
  3. One camera, simple mode: `scripts/install-fedora.sh --mode simple --cameras a`
     (bench test in daytime: add `--ignore-schedule`, then re-run without it).
  4. Watch it: `sudo journalctl -u sentinel-recorder -f`.

## If something goes wrong

| Situation | Recovery |
| --- | --- |
| Pull or rebase made a mess | `git rebase --abort` or `git merge --abort`; local work is in the stash and in `$BK` |
| Stash apply went wrong | Do not discard with `checkout`/`restore`. `git stash push -u -m "bad-apply-$TS"` to park the bad attempt, then `git stash apply "$STASH"` again |
| Lost a local file | `tar -xzf "$BK/local-untracked.tgz" <path>` or `git apply "$BK/local-tracked.patch"` on a scratch branch |
| Need the original tree exactly | `git switch -c recover "backup/deploy-pc-$TS" && git apply "$BK/local-tracked.patch" && tar -xzf "$BK/local-untracked.tgz"` |
