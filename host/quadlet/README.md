# Quadlet units

Install under `/etc/containers/systemd/` as root, then
`systemctl daemon-reload`. Enabling the `.container` units starts them at boot.
The `.volume` files are dependencies of those units (Podman names the volumes
`systemd-frigate-config` and so on). Commands are in [../RUNBOOK.md](../RUNBOOK.md).

| File | systemd unit | Image |
| --- | --- | --- |
| `mosquitto.container` | `mosquitto.service` | `docker.io/library/eclipse-mosquitto:2` |
| `frigate.container` | `frigate.service` | `ghcr.io/blakeblackshear/frigate:0.18.1` |
| `mosquitto-data.volume` | volume dependency | broker persistence |
| `frigate-config.volume` | volume dependency | `/config` (database, model cache) |
| `frigate-media.volume` | volume dependency | `/media/frigate` recordings |

`host/scripts/pin-digests.sh` replaces each installed `Image=` line with
`name:tag@sha256:…` and writes `secrets/digests.txt`. The copies in git keep
the tags because the digest is recorded when Fedora pulls. Do not start the
units before that pin. Re-running the script after a later pull moves the pin;
do not pull a newer Frigate tag than `0.18.1`.

Both containers use `Network=host` so Frigate can open `10.77.0.11` on the AP
and mosquitto can bind `10.77.0.1`. Published ports are not used. go2rtc and
the Frigate UI bind localhost in `frigate/config.yml`.

Frigate gets `/dev/dri/renderD128` and `/dev/dri/card0`, `ShmSize=256m`, and a
1 GB tmpfs on `/tmp/cache` (sizes from `docs/vendor/frigate` installation.md:
128MB is the documented shm for two 720p detect streams, plus up to about 40MB
of logs in shm; the segment cache example there is 1000000000 bytes). Volume
mounts use the SELinux `:Z` label. `StopTimeout=30` matches the upstream
compose example's stop grace for Frigate.

`frigate.service` `Requires=mosquitto.service`. Mosquitto restarts until
`10.77.0.1` exists, which is after NetworkManager brings up `sentinel-ap`.

Logs: `journalctl -u frigate` and `journalctl -u mosquitto`.

Do not install a distro `mosquitto.service` beside this unit.

`sentinel-controller.container` and `sentinel-evidence.volume` belong to the
controller already in `host/controller/`. Leave them disabled for the Phase 2
exit. That unit expects host networking, `http://127.0.0.1:5000`, and MQTT user
`controller` on `10.77.0.1:1883`, which is what the Frigate listen address and
the mosquitto ACL provide.

`sentinel-recorder.container` and `sentinel-recordings.volume` are simple mode.
`install-services.sh --mode` installs one mode's `.container` files and removes
the other's. Quadlet units are not `systemctl disable`d; deleting the file and
`daemon-reload` turns that mode off. The recordings volume stays across the switch.
