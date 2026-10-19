# Fedora runbook

## Automated path

```sh
scripts/install-fedora.sh
```

does steps 2 through 5 below and the controller: it generates the secrets, detects the AP
interface, scans for a quiet channel, turns off Wi-Fi client autoconnect, creates the hidden AP,
records its BSSID, pins and installs the images and units, and starts mosquitto, Frigate and
sentinel-controller as system services that return after a reboot. It refuses to touch the
radio if the default route is on Wi-Fi. Run step 1 (the probe) first if you want to see the
hardware before anything changes. The numbered steps stay as the manual equivalent and as the
checklist for what the script did; steps 6 and 7 (camera, human exit check) are still yours.
That install is Frigate mode. Simple mode is [below](#simple-mode).

Flash the cameras with `scripts/install-esp32.sh all`; they boot already bound to this host.

Do this on the Fedora cubicle box, from a checkout of this repo. The Arch
machine where these files were written cannot prove the AP, VAAPI, OpenVINO, or
person detection. Pasting this runbook's commands there does not finish Phase 2.

Stop after step 1 if the probe shows no AP mode or a CPU older than Intel 6th
generation. That is the host-probe escalation in
[../docs/phases/README.md](../docs/phases/README.md), not this runbook.

Packages if they are missing:

```sh
sudo dnf install iw pciutils podman
```

NetworkManager and firewalld should already be running. Do not install the
distro `mosquitto` package; the broker is the container below. If
`systemctl cat mosquitto.service` already exists and is not a Podman Quadlet,
stop and remove that package before enabling the unit in step 5.

## 1. Probe

```sh
host/scripts/probe-host.sh | tee /tmp/sentinel-probe.txt
```

Read `/tmp/sentinel-probe.txt` before changing the network.

- **CPU.** OpenVINO on the iGPU needs Intel 6th gen (Skylake) or newer. A model
  number `i7-6700` is 6th gen; `i7-10xxx` and later, and Core Ultra, are newer.
  If the model name is not an Intel Core generation you can identify, stop.
- **Wi-Fi.** `iw list` must show `AP` under Supported interface modes, and a
  valid interface combination that can run an AP. Note the interface name from
  `iw dev` (often `wlp…`). That name is `WIFI_IFACE`. Ethernet is the uplink;
  do not use a USB Wi-Fi stick unless the built-in interface has no AP mode.
- **GPU.** `ls /dev/dri` should list `card0` and `renderD128` (names can differ).
  The Quadlet `AddDevice=` lines must match this listing.
- **Routes.** `ip -4 route` should already show the default route on Ethernet.
  Keep that output to compare after the AP is up.

If there is no AP mode, or the CPU is older than 6th gen: stop. Do not run
`setup-ap.sh`.

## 2. Turn off Wi-Fi client autoconnect

The built-in radio is the camera AP only. For every saved Wi-Fi **client**
profile (not `sentinel-ap`):

```sh
nmcli -f NAME,TYPE,AUTOCONNECT connection show
nmcli connection modify 'PROFILE NAME' connection.autoconnect no
nmcli connection down 'PROFILE NAME'
```

`setup-ap.sh` refuses to continue while another Wi-Fi profile still
autoconnects, or while the chosen interface is associated to a client network.

## 3. Secrets, channel, and the AP

```sh
host/scripts/generate-secrets.sh
```

Edit `secrets/ap.env`:

- `WIFI_IFACE` from step 1.
- `CHANNEL` is `1`, `6`, or `11`. Scan before the AP exists:

```sh
nmcli dev wifi list ifname "$WIFI_IFACE"
```

Pick the quietest of 1, 6, and 11. Leave the generated SSID and PSK. The SSID
must not contain `SENTINEL`.

```sh
sudo host/network/setup-ap.sh
```

The script installs firewalld zone `sentinel` (target `DROP`, TCP 1883 only),
creates a hidden 2.4 GHz AP at `10.77.0.1/24` with `ipv4.method manual` and
`ipv4.never-default yes`, and does not enable DHCP, NAT, or masquerade. WPA is
WPA2-PSK with PMF disabled so the ESP32 station firmware can associate.

Confirm on the host:

- `ip -4 route` default is still Ethernet, not the Wi-Fi interface.
- `iw dev "$WIFI_IFACE" info` shows type AP, the channel you set, and an `addr`
  (BSSID). Write the BSSID in your notes. Do not commit it.

Phone test, static addressing (do not use `.11`–`.13`; those are cameras):

| Field | Value |
| --- | --- |
| SSID | value of `SSID` in `secrets/ap.env` (hidden; type it in) |
| Password | value of `PSK` |
| IP | `10.77.0.50` |
| Prefix | `255.255.255.0` (`/24`) |
| Gateway | `10.77.0.1` |
| DNS | blank |

Then:

- A website does not load (no NAT to Ethernet, no internet).
- `http://10.77.0.1:1883` from the phone fails as HTTP, but the attempt means
  TCP reached the host only after mosquitto is installed in step 5. Before
  that, the port is closed. Re-check after step 5: 1883 accepts a TCP
  connection, and `5000`, `8554`, `8555`, `8971`, and `1984` do not.
- The phone cannot open other hosts on the corporate LAN.

## 4. Pull images and record digests

```sh
sudo host/scripts/pin-digests.sh
```

This pulls `ghcr.io/blakeblackshear/frigate:0.18.1` and
`docker.io/library/eclipse-mosquitto:2` into the **root** Podman store, writes
`secrets/digests.txt`, and rewrites `Image=` in
`/etc/containers/systemd/*.container` if those units are already installed.
If the units are not installed yet, run it again after step 5's copy. Do not
start the services on the floating tags.

Hashes for mosquitto (also root, same image store):

```sh
sudo host/scripts/hash-mqtt-passwords.sh
```

That reads `secrets/mosquitto/users` and writes `secrets/mosquitto/passwords`.

## 5. Install Quadlet units

```sh
sudo install -d -m 0755 /etc/sentinel/frigate /etc/sentinel/mosquitto /etc/containers/systemd
sudo install -m 0644 host/frigate/config.yml /etc/sentinel/frigate/config.yml
sudo install -m 0644 host/mosquitto/mosquitto.conf /etc/sentinel/mosquitto/mosquitto.conf
sudo install -m 0644 host/mosquitto/acl.example /etc/sentinel/mosquitto/acl
sudo install -m 0600 secrets/mosquitto/passwords /etc/sentinel/mosquitto/passwords
sudo install -m 0600 secrets/frigate.env /etc/sentinel/frigate.env
sudo install -m 0644 host/quadlet/mosquitto.container /etc/containers/systemd/mosquitto.container
sudo install -m 0644 host/quadlet/frigate.container /etc/containers/systemd/frigate.container
sudo install -m 0644 \
    host/quadlet/mosquitto-data.volume \
    host/quadlet/frigate-config.volume \
    host/quadlet/frigate-media.volume \
    /etc/containers/systemd/
sudo host/scripts/pin-digests.sh
sudo systemctl daemon-reload
sudo systemctl enable --now mosquitto.service frigate.service
```

`pin-digests.sh` the second time rewrites the installed `Image=` lines to
`name:tag@sha256:…` and reloads systemd. Enable after that rewrite.

If `AddDevice=` fails because a node from step 1 is missing, edit
`/etc/containers/systemd/frigate.container` so the device lines match
`ls /dev/dri`, then `sudo systemctl daemon-reload` and start again.

```sh
systemctl status mosquitto.service frigate.service
journalctl -u frigate -e
ss -ltn | awk '$4 ~ /:(1883|1984|5000|8554|8555|8971)$/'
```

Expected listeners:

| Port | Address | What |
| --- | --- | --- |
| 1883 | `127.0.0.1` and `10.77.0.1` | mosquitto |
| 1984, 8554, 8555 | `127.0.0.1` | go2rtc API, RTSP, WebRTC |
| 5000 | `127.0.0.1` | Frigate internal API, no auth |
| 8971 | `127.0.0.1` | Frigate UI |

UI: `https://127.0.0.1:8971` (self-signed; see the drift note in
[README.md](README.md)). The first admin password is printed once in
`journalctl -u frigate`. Set a new one under Settings → Users. Port 5000 stays
on localhost; a later controller on the host network can call
`http://127.0.0.1:5000`.

First start downloads the face-recognition models over Ethernet
(`network_requirements.md`). They cache in the config volume. The OpenVINO
detection model is already in the image.

Repeat the phone check from step 3 now that 1883 is open. From the phone, TCP
to `10.77.0.1:1883` should succeed and the other ports above should not.
An MQTT client can log in as `cam_a` with the password in
`secrets/mosquitto/users`. Anonymous connections are refused.

If the GPU is denied, check `journalctl -u frigate` and `ausearch -m avc -ts recent`.
Rootful Podman usually reaches `/dev/dri`. The rootless note in the Quadlet
docs is `setsebool -P container_use_devices=true`; only do that if an AVC says
the device label is the reason. Do not turn SELinux off.

If Frigate exits with `Bus error`, raise `ShmSize=` (vendored install docs:
128MB is the figure for two 720p detect streams; this unit uses 256m).

## 6. Point Frigate at the bench camera

`sentinel_a` is `http://10.77.0.11/stream?token=…` (CONTRACTS.md). Give the
Phase 1 board that address on the AP: `10.77.0.11/24`, gateway `10.77.0.1`.
Phase 1 ignores the token; leave the query parameter in place.

Join the board with the hidden SSID, PSK, and the BSSID/channel from step 3 if
the firmware already pins them. One stream client at a time; go2rtc is that
client.

Watch the log:

```sh
journalctl -u frigate -f
```

The go2rtc line must not contain the literal text `{FRIGATE_STREAM_TOKEN_A}`.
If it does, Frigate did not substitute the stream URL (the reference config
does not list that field; `advanced/system.md` says container env vars are what
go2rtc can see). Then:

```sh
sudo host/scripts/render-frigate-config.sh --force
sudo systemctl restart frigate.service
```

That writes `/etc/sentinel/frigate/config.yml` with only the token filled in.
MQTT still uses `{FRIGATE_MQTT_*}` from `/etc/sentinel/frigate.env`. Do not copy
that rendered file back into git.

A temporary bench address other than `10.77.0.11` is a one-line edit of the
`ffmpeg:http://…` URL in the installed config. Put `10.77.0.11` back before
calling the phase done.

In the UI, the camera should show a live image, and System → Metrics should
list the OpenVINO detector on `GPU`.

## 7. Human exit check

Walk through the camera's view.

- Review shows an alert whose label is `person`.
- History for that alert includes about 10 seconds before you appear. Segment
  boundaries are 10 seconds, so the edge can be a few seconds off. The Explore
  clip is trimmed to the tracked object and will not show the pre-roll; use
  History (`record.md`).
- System page inference is under about 20 ms.

Face library: when you enroll, enroll only yourself. Do not do that as part of
standing up this phase.

## Reboot

`sentinel-ap` autoconnects, then the enabled Quadlet units start. Mosquitto
listens on `10.77.0.1` and restarts until that address exists. After a reboot,
repeat the route check (`ip -4 route`) and `systemctl status frigate`.

## Simple mode

The steps above install Frigate mode. Simple mode records each camera's JPEG
frames when the picture changes, and Mosquitto stays up so camera telemetry
keeps working. The camera serves one stream client, so this mode and Frigate
mode take turns.

```sh
scripts/install-fedora.sh --mode simple --cameras a
```

`--cameras a,b` or `a,b,c` adds the others. Switch back with
`scripts/install-fedora.sh --mode frigate`.

```sh
journalctl -u sentinel-recorder -f
```

Recording is allowed at all times except Monday–Friday 06:00–16:00 in the
host's local timezone: movement from 4:00 pm to 6:00 am on weekdays, and any
time on Saturday and Sunday. A weekday afternoon bench test ignores that window
for one run. The flag is not saved; the next run puts the schedule back:

```sh
sudo host/scripts/install-services.sh --mode simple --ignore-schedule --cameras a
sudo host/scripts/install-services.sh --mode simple --cameras a
```

Events land on the recordings volume, one directory per stretch of motion:

```text
/var/lib/containers/storage/volumes/sentinel-recordings/_data/sentinel_a/<date>/<time>/frames/
```

Open `frames/` in any image viewer, or `mpv "mf://frames/*.jpg" --mf-fps=5`.
`latest.jpg` beside the date directories is a recent frame for aiming:

```sh
sudo cp /var/lib/containers/storage/volumes/sentinel-recordings/_data/sentinel_a/latest.jpg /tmp/sentinel_a-latest.jpg
```

The schedule check prints `allowed` or `quiet` (exit 0 or 1):

```sh
sudo podman exec sentinel-recorder sentinel-recorder check-schedule
sudo podman exec sentinel-recorder sentinel-recorder check-schedule --at 2026-10-19T17:00
```

`--at` without a zone offset is the timezone in `/etc/sentinel/recorder.toml`.
If the recorder exits with code 2, or `systemctl status sentinel-recorder` shows
a restart loop, it cannot read `/etc/sentinel/recorder.toml` (that file must be
mode 0644). Re-run the installer.
If that restart loop is the recordings directory not being writable, the
volume's top directory is not owned by uid 1000. Re-run the installer; it
chowns that directory and leaves the frames under it alone.
Quadlet units are not turned off with `systemctl disable`. Switching mode
removes the other mode's `.container` file and runs `systemctl daemon-reload`.
The recordings volume and `/etc/sentinel/frigate*` stay on disk.

## What not to commit

`secrets/`, `/etc/sentinel/frigate.env`, `/etc/sentinel/recorder.env`, mosquitto
`passwords`, probe output, and any config copy whose token was rendered into the URL.
