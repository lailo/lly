# lly

A small, fully-typed Python CLI + TUI to discover and manage your
**Shelly Gen2 / Gen3** devices on the LAN.

- Scan the network with mDNS, pick which devices to track
- Live status table: firmware, on/off for switches, open/closed + position for covers
- Bulk **reboot** and **OTA firmware update** with multi-select
- All state in plain TOML under your platform config dir
  (`~/Library/Application Support/lly/` on macOS, `~/.config/lly/` on Linux)

> Gen1 (`shelly1`, `shelly2.5`, original `shellyDimmer`, ...) is intentionally
> out of scope — Gen2/Gen3 only.

---

## Requirements

- macOS or Linux
- [`uv`](https://docs.astral.sh/uv/) installed
  ```sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- Python 3.12+ (uv will install it for you on first run if missing)
- Your Shellies reachable on the same L2 network (mDNS must not be blocked
  between your machine and the devices — VLAN segregation often breaks this)

## Install / first run

From the project root:

```sh
uv sync               # installs deps into .venv
uv run lly --help     # check the CLI is wired up
```

That's it — no `pip install`, no global state. Every command below is run via
`uv run`.

If you want a bare `lly` command on your `$PATH`, install the package as a uv
tool:

```sh
uv tool install --editable .
lly --help
```

## Configure your default password

Most home setups have **one shared password** on all Shelly devices (username
is always `admin` on Gen2/3). Save it once:

```sh
uv run lly config set-password
# Default Shelly password (empty to clear): ********
```

This writes (encrypted-at-rest only by your filesystem permissions, **not**
encrypted at the app level) to `config.toml` in your platform config dir (see
"File layout" below).

You can override per-device later by editing `devices.toml` in the config dir and
adding `password_override = "..."` to a specific entry.

Inspect your config any time:

```sh
uv run lly config show
```

## Adding devices

### Option A — interactive TUI

```sh
uv run lly
```

In the TUI:

| Key     | Action                                             |
| ------- | -------------------------------------------------- |
| `s`     | Open the mDNS scan modal                           |
| `space` | Toggle selection on the row under the cursor       |
| `a`     | Select all / clear selection                       |
| `R`     | Refresh status now                                 |
| `r`     | Bulk **reboot** selected (or all if none selected) |
| `u`     | Bulk **update** selected (or all if none selected) |
| `q`     | Quit                                               |

Inside the scan modal:

| Key      | Action                              |
| -------- | ----------------------------------- |
| `space`  | Toggle pick on the row under cursor |
| `a`      | Pick all / none                     |
| `enter`  | Import picked rows                  |
| `escape` | Cancel                              |

Imported devices are merged into `devices.toml` in your config dir. Your custom
names and per-device password overrides are preserved across re-imports.

### Option B — non-interactive CLI

```sh
uv run lly scan                # one-shot scan, prints a table, doesn't save
uv run lly add --yes           # scan and import everything found
uv run lly add                 # scan, then prompt for which ids to import
uv run lly list                # show the saved fleet
```

## Daily use

```sh
uv run lly status              # live state of every saved device
uv run lly status shellyplus1pm-aabbccddeeff   # one device

uv run lly action reboot                      # reboot all
uv run lly action reboot shellyplus1pm-aabb   # reboot one
uv run lly action update shellyplus1pm-aabb   # OTA via official Shelly server
```

The TUI auto-refreshes status every 5 s (configurable in `config.toml`).

OTA note: `Shelly.Update` against the official firmware server is a
**no-op** when a device is already on the latest stable firmware — that
surfaces as a `[red]err[/]` row with message `no update available`. That's
not a real failure; expect it most of the time.

## File layout (what gets saved where)

```
# macOS:  ~/Library/Application Support/lly/
# Linux:  ~/.config/lly/
<config-dir>/
├── config.toml      # default password, scan timeout, refresh interval
├── devices.toml     # the curated fleet
└── lly.log          # JSON-Lines log, rotated at 1 MB
```

The exact location follows `platformdirs.user_config_dir("lly")`; both
`config.toml` and `devices.toml` are written `0600` because they contain
plaintext device passwords.

`devices.toml` is plain TOML — feel free to hand-edit, rename, or remove
entries. The format:

```toml
[[devices]]
id = "shellyplus1pm-08b61fcaaabb"
name = "kitchen light"
host = "192.168.1.42"
model = "Plus1PM"
gen = 2
kind = "switch"
fw_version = "1.4.4"
# password_override = "device-specific-password"   # optional
```

## Development

```sh
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy                      # strict typecheck
uv run pytest -q                 # tests (25 of them, all offline)
```

The codebase is `from __future__ import annotations` everywhere, `mypy
--strict`, and tested with `respx` mocks for the HTTP layer and `MagicMock`
fakes for `zeroconf`. No real network is needed to run the test suite.

Project layout:

```
src/lly/
├── cli.py              # Typer entry point (`lly`)
├── config.py           # XDG paths, atomic TOML I/O, merge logic
├── discovery.py        # async zeroconf scanner for _shelly._tcp.local.
├── fleet.py            # parallel status refresh + bulk action runners
├── models.py           # Pydantic models, kind inference
├── shelly/
│   ├── client.py       # httpx async client with Digest auth + RPC envelope
│   └── rpc.py          # typed wrappers: GetStatus, Reboot, Update, ...
└── tui/
    ├── app.py
    └── screens/        # MainScreen, ScanScreen, BulkScreen
```

## Troubleshooting

**Scan finds nothing.** mDNS uses UDP/5353. Check:

- The Shellies and your machine are on the same VLAN/SSID
- mDNS isn't filtered by your router or AP (Unifi calls it "IGMP snooping" /
  "multicast enhancement"; aruba/cisco have similar)
- The devices are actually Gen2/3 — `gen` must appear in their TXT record

You can sanity-check with:

```sh
dns-sd -B _shelly._tcp .   # macOS
avahi-browse -r _shelly._tcp   # Linux
```

**`401 Unauthorized` on every RPC.** Your device has a web UI password set
and `lly config set-password` either wasn't run or the password is wrong.
The username is always `admin` (Shelly Gen2+) — you cannot change it.

**OTA always says "no update available".** That's not an error — it's
`Shelly.Update` reporting your firmware is current. Run
`uv run lly status` to confirm `fw_version` matches the latest Shelly
stable channel.

## License

MIT, with the [Commons Clause](https://commonsclause.com/) condition layered
on top — see [`LICENSE`](LICENSE). In plain English: use it, fork it, modify
it, distribute it freely; just don't **sell** it (or a hosted/consulting
service whose value derives substantially from it). Personal and internal use
at your company is fine.

Note: the Commons Clause makes this _source-available_, not OSI-approved open
source.
