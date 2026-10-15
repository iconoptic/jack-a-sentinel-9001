# Camera AP

Ethernet is the host uplink. The built-in Wi-Fi is only the camera AP.
`setup-ap.sh` is idempotent enough to re-run: it updates connection
`sentinel-ap` if that profile already exists.

Full procedure: [../RUNBOOK.md](../RUNBOOK.md). Apply this directory in this order:

1. `host/scripts/probe-host.sh` on Fedora. Stop if there is no AP mode or the
   CPU is older than Intel 6th gen.
2. Turn off autoconnect on saved Wi-Fi client profiles and disconnect them.
3. `host/scripts/generate-secrets.sh`, then set `WIFI_IFACE` and `CHANNEL` in
   `secrets/ap.env`. Scan first (`nmcli dev wifi list ifname …`) and use
   channel 1, 6, or 11.
4. `sudo host/network/setup-ap.sh`
5. Phone test below. The broker port is only open after mosquitto is installed
   (runbook step 5).

## What the script sets

| Item | Value |
| --- | --- |
| Address | `10.77.0.1/24`, `ipv4.method manual` |
| Default route | `ipv4.never-default yes`, gateway cleared. Ethernet keeps the default route. |
| SSID | Hidden (`802-11-wireless.hidden yes`). Name comes from secrets, not git. |
| Band | `bg` (2.4 GHz), channel width 20 MHz, fixed channel from secrets |
| Security | `wpa-psk`, protocol `rsn`, CCMP, PMF `disable` (WPA2, not WPA3 transition) |
| IPv6 | `ipv6.method disabled` |
| DHCP / NAT | Not configured. `ipv4.method shared` is never set. |
| Firewall | Zone file `sentinel-zone.xml` installed as `/etc/firewalld/zones/sentinel.xml`. Target `DROP`. TCP `1883` only. No masquerade. |
| Power save | Disabled on the AP profile |

The script reads `secrets/ap.env` (override with `SENTINEL_AP_ENV`). It does not
print the PSK. It exits if another Wi-Fi profile still autoconnects, if the
interface is on a client connection, if the address is not `10.77.0.1/24`, if
the default route lands on the Wi-Fi interface, or if firewalld puts that
interface in a zone other than `sentinel`.

`net.ipv4.ip_forward` is printed and not changed. Podman may set it to `1` for
its own bridges. This zone has no masquerade. After the script, check
`firewall-cmd --list-all-policies` and confirm nothing forwards zone `sentinel`
to the Ethernet zone.

The script does not set the Wi-Fi regulatory domain. If the AP fails to start
on the chosen channel, check `iw reg get` from the probe output before changing
it.

## Phone test

Static IP `10.77.0.50/24`, gateway `10.77.0.1`, DNS blank, hidden SSID and PSK
from `secrets/ap.env`. Do not use `10.77.0.11`–`10.77.0.13`.

The phone can open TCP `10.77.0.1:1883` once mosquitto is up, and cannot open
the internet, the corporate LAN, or Frigate's ports. On the host, `ip -4 route`
still shows the default route via Ethernet.

`iw dev <iface> info` after the script prints the BSSID (`addr`) and channel.
Keep them for a later bind payload. Do not commit them.
