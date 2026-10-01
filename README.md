# Barco Pulse

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration for **Barco** projectors on the **Pulse** platform (Balder, Loki, Bragi and others). It
uses the projector's JSON-RPC API on TCP port 9090 and keeps one session open. Changes are pushed by the projector;
a 30-second poll reconnects and notices when a sleeping projector wakes up. It has no Python dependencies other than
`wakeonlan`.

## Setup

**Settings → Devices & services → Add integration → Barco Pulse**, then enter:

- **Host**: the projector's IP address or hostname.
- **MAC address**: in any common format. In eco mode the projector drops off the network, and turning it on sends a
  wake-on-LAN packet to this address.
- **PIN code** (optional): the projector's control PIN. Without it the projector can be monitored but not controlled.

The projector must be awake (not in eco mode) to be added.

## Entities

| Entity | What it does |
|---|---|
| `media_player` | Power and input. On while the laser is on or warming up. Stays available while the projector is asleep, so turning it on can wake it. The attributes `system_state` and `target_state` carry the projector's own state names. |
| `remote` | Power, and `remote.send_command` with any parameterless JSON-RPC method (e.g. `system.gotoready`, `system.gotoeco`). |
| `sensor` Inlet / Outlet / Mainboard temperature | °C, shown in your unit system. |
| `sensor` Input signal, Output resolution, Output width / height, Laser state | Signal and processing details. |
| `sensor` State, Target state | `boot`, `eco`, `standby`, `ready`, `conditioning` (warming up), `on`, `service`, `deconditioning` (cooling down), `error`. |
| `sensor` Health | `normal`, `warning` or `error`, as the projector reports it. |
| `binary_sensor` Laser, Illumination, HDMI signal | On/off. |
| `binary_sensor` Health problem | On when the projector's health isn't Normal. |

Readings go unavailable while the projector is asleep or unreachable.

## Upgrading from barco_pulse (domain `Barco`)

Install this integration in place of the old one, restart, then add **Barco Pulse** and choose **Import the existing
projector**. The old entry's settings, device, entity IDs, names and history carry over. Unique IDs change from
`Barco:<mac>_<key>` to `<mac>_<key>`, and the old entry is removed.

Changes from the old package that you may notice:

- The media player is `off` (not `idle`) while the projector isn't projecting.
- Temperatures are reported in °C and converted to your unit system, so they still show in °F on an imperial system.
- Sensor names are proper names ("Inlet temperature") rather than keys ("inlet_temp").
- The media player stays available while the projector is asleep, so it can be turned on from Home Assistant.

## License

MIT. See [LICENSE](LICENSE).
