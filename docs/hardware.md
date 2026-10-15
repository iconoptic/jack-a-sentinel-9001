# Hardware notes

## The board

FORIOT "ESP32-S3-CAM", 3-pack (Amazon). This is a common generic layout with no
vendor schematic, so everything below comes from the closest documented clone,
the **Keyestudio MB0200 S3 CAM**: same ESP32-S3-WROOM-1-N16R8 module, same OV3660,
same CH340C + OTG dual USB-C layout. Treat it as *expected*, not confirmed, until
Phase 1 bring-up checks it ([PLAN.md](PLAN.md#phase-1-bench-bring-up-one-board)).

Local copy: `docs/vendor/hardware/keyestudio-MB0200-S3-CAM.md`

| Item | Value |
| --- | --- |
| Module | ESP32-S3-WROOM-1 **N16R8**: 16 MB quad flash, 8 MB **octal** PSRAM |
| Radio | 2.4 GHz Wi-Fi b/g/n, **Bluetooth LE 5 only (no Classic BT)** |
| Camera | OV3660, 3 MP, max 2048×1536, DVP interface, hardware JPEG |
| USB-C #1 | CH340C USB-UART: flashing + logs. Auto-reset into the bootloader should work. |
| USB-C #2 | Native ESP32-S3 USB OTG (GPIO19/20): USB-Serial-JTAG or TinyUSB device |
| SD slot | SDMMC 1-bit: CMD=IO38, CLK=IO39, D0=IO40 (the FORIOT board may not have one; check) |
| Buttons | RST, BOOT (GPIO0, a strapping pin). BOOT doubles as the factory-reset button. |

### Camera pinout (matches the ESP32-S3-EYE layout)

In Arduino this is `CAMERA_MODEL_ESP32S3_EYE`. In ESP-IDF, put these values in `camera_config_t`.

| Signal | GPIO | | Signal | GPIO |
| --- | --- | --- | --- | --- |
| PWDN | -1 (not wired) | | Y9 (D7) | 16 |
| RESET | -1 (not wired) | | Y8 (D6) | 17 |
| XCLK | 15 | | Y7 (D5) | 18 |
| SIOD (SDA) | 4 | | Y6 (D4) | 12 |
| SIOC (SCL) | 5 | | Y5 (D3) | 10 |
| VSYNC | 6 | | Y4 (D2) | 8 |
| HREF | 7 | | Y3 (D1) | 9 |
| PCLK | 13 | | Y2 (D0) | 11 |

The camera, SD and PSRAM take most of the free pins. PSRAM in octal mode takes
GPIO33–37, so don't use those.

## Power

### Draw per board

The 3.3 V regulator on these boards is almost certainly linear, so current at 5 V is
about the same as current at 3.3 V.

| Load | Current | Source |
| --- | --- | --- |
| Wi-Fi TX burst | 286–355 mA peak | WROOM-1 datasheet, Table 6-4 (355 mA is 802.11b at full power) |
| Wi-Fi RX / listening | ~95 mA | same table |
| CPU + PSRAM, streaming | ~40–60 mA | estimate from Table 6-6 plus PSRAM |
| OV3660 active | ~60–100 mA | estimate; no public datasheet |
| CH340C, LEDs | ~10–20 mA | estimate |
| **Per board, streaming** | **~200–300 mA average, ~500 mA peak** | Espressif requires a supply rated **≥ 0.5 A per module** |
| **Three boards** | **~0.9 A average, 1.5 A worst-case peak** | |

Measure the real numbers in Phase 1 with an inline USB power meter.

### One supply, one custom three-way cable

Yes, this works. USB here carries power only, since video goes over Wi-Fi, so the
harness needs just **5 V (VBUS) and GND**. Leave D+ and D− unconnected. The thing to
design around is **voltage drop**, not the splicing. The regulator needs about 4.5 V
at the board. Below that, Wi-Fi TX bursts cause brownout resets.

Most USB cables have very thin power wires (28 AWG). That's why splicing ordinary
cables end to end fails. Maximum run length for a 0.5 V drop (round trip, copper):

| Wire | Shared trunk, all 3 boards (1.5 A) | Single-camera branch (0.5 A) |
| --- | --- | --- |
| 28 AWG (typical USB cable) | 0.8 m | 2.3 m |
| 24 AWG ("charging" USB cable) | 2.0 m | 6.0 m |
| 22 AWG | 3.1 m | 9.4 m |
| **20 AWG** | **5.0 m** | 15 m |
| **18 AWG** (lamp/zip cord) | **7.9 m** | 24 m |

These are worst-case limits: all three boards at peak at once, at the far end. In
practice you get some headroom.

**Build:**

- **Source:** a 5 V supply rated ≥ 3 A. Use a plain 5 V DC adapter, or a USB-A charger
  port, which always outputs 5 V without negotiation. Avoid sourcing from a USB-C PD
  charger through a spliced cable: those only enable 5 V when they detect a proper
  sink on the CC pins.
- **Trunk:** 18–20 AWG two-conductor wire (zip cord or speaker wire), either a Y/star
  split or taps along a run. **Each branch** can be 22–24 AWG if it is short.
- **At each camera:** a short **USB-C power-only pigtail** (VBUS + GND), or wire to the
  board's **5V and GND header pins**. With the header option, don't plug a computer into
  the board's USB while the harness is connected unless you have confirmed a diode on
  VBUS, or the harness will backfeed the computer's port. Flash before mounting; OTA
  updates later remove the need for a cable.
- **Bulk capacitor:** **470–1000 µF, ≥ 10 V** electrolytic across 5 V/GND at each
  camera end. Watch the polarity. It absorbs Wi-Fi TX spikes, so the long wire doesn't
  have to.
- **Safety:** a 2–3 A inline fuse or polyfuse at the supply, heat-shrink on every splice
  (not tape), strain relief at each pigtail, and check polarity with a multimeter before
  the first plug-in.

## Things to verify on real hardware (Phase 1)

- [ ] `esptool chip-id` and `flash-id` report ESP32-S3 with 16 MB flash, and the boot log shows 8 MB octal PSRAM
- [ ] The camera probe reports an OV3660 (PID `0x3660`) and not an OV2640. Some FORIOT listings ship OV2640.
- [ ] Which USB-C port is the CH340 and which is native USB. Label them.
- [ ] Whether an SD slot is populated
- [ ] Onboard LED and RGB LED GPIOs, if any
- [ ] Achievable frame rates at VGA/SVGA/HD over Wi-Fi at the planned distance to the AP
- [ ] Board temperature after 30 min of continuous streaming. These boards run hot, so they may need a heatsink or a lower XCLK.
- [ ] Current draw while streaming, average and peak, using an inline USB meter. Compare with [Power](#power).
- [ ] Marking on the 3.3 V regulator chip. An AMS1117 needs ≥ 4.4 V in; a low-dropout part (ME6211, etc.) tolerates more drop.
- [ ] No brownout resets after 1 h at the end of a test harness wire of the planned length (check reset reason in the logs)

## Host (Fedora box)

| Item | Value | Implication |
| --- | --- | --- |
| CPU | Intel i7 (generation TBD) | AVX2 is present on any i7 from 4th gen on, enough for face recognition on the CPU |
| Graphics | Intel integrated | OpenVINO detector on the iGPU (6th gen or newer) and VAAPI for the MJPEG→H.264 transcode |
| Disk | >500 GB free | Plenty: 3 cameras × a 1-day rolling buffer plus months of alert clips |
| Wi-Fi | Built-in (Intel) | **Dedicated to the hidden camera AP.** Confirm AP support with `iw list`. |
| Bluetooth | Built-in | Used once per camera by `sentinel-provision` (BlueZ). No extra hardware needed. |
| Uplink | **Ethernet** (primary) | Stays the default route. The camera AP is isolated from it, with no forwarding. |

Fill in the exact models in Phase 2 (`lscpu`, `lspci -k`, `iw list`, `ls /dev/dri`).
