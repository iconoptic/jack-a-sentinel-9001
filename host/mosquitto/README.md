# mosquitto

Image: `docker.io/library/eclipse-mosquitto:2`, pinned by digest on Fedora
([../RUNBOOK.md](../RUNBOOK.md)). Config in this directory is installed to
`/etc/sentinel/mosquitto/`.

## Listeners

`mosquitto.conf` has two listeners on port 1883:

- `127.0.0.1` for Frigate (and later the controller) in the host network namespace
- `10.77.0.1` for cameras on the AP

Anonymous clients are refused. firewalld zone `sentinel` is what allows 1883
from the AP interface and drops everything else. Do not also open 1883 on the
Ethernet zone.

The container starts as root (`User=0` in the Quadlet) so the image entrypoint
can chown the mounts and drop to the `mosquitto` user. The password file is
mode `0600`. Mounts are writable because that chown runs against them.

If `10.77.0.1` is not configured yet, the process exits and systemd restarts it
(`Restart=on-failure`).

## ACL and passwords

`acl.example` is the ACL to install. It has no secrets.

| User | Allowed |
| --- | --- |
| `frigate` | read/write `frigate/#` |
| `cam_a` | write `sentinel/a/#`, read `sentinel/a/cmd` |
| `controller` | read `frigate/#` and `sentinel/#`, write `sentinel/+/cmd` |

`controller` matches `host/controller` (`username = "controller"`). Cameras `b`
and `c` stay commented until the provision CLI appends them on the installed
file `/etc/sentinel/mosquitto/acl`.

The controller password is the `controller:` line in `secrets/mosquitto/users`,
also written with no trailing newline to `secrets/mosquitto/controller.password`
for the Quadlet secret:

```sh
sudo podman secret create sentinel-controller-mqtt-password secrets/mosquitto/controller.password
```

That secret is for `sentinel-controller.container`. Phase 2 does not start that unit.

`passwords.example` shows the plaintext shape. Generate the real lines with
`host/scripts/generate-secrets.sh` (`secrets/mosquitto/users`), then hash them
on Fedora with `host/scripts/hash-mqtt-passwords.sh` using the image's
`mosquitto_passwd`. Install the hashed file as
`/etc/sentinel/mosquitto/passwords`.
