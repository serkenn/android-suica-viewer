# Suica Viewer

Suica Viewer is a tool for retrieving, displaying, and saving detailed information from FeliCa-based transit IC cards. It uses a remote authentication server to read encrypted areas and offers two entry points: a console-oriented CLI and a Tkinter-based GUI.

## Key Features
- Mutual authentication with a remote server to read encrypted areas
- CLI version: formatted text output for issuance data, balance, history, commuter pass details, and more
- GUI version: visual viewer with tabs for Overview, Issuance Info, Transaction History, Gate History, and Other; includes history filtering and JSON copy/save actions
- Resolves company, line, and station names based on `station_codes.csv`
- Switch authentication servers via the `AUTH_SERVER_URL` environment variable (default: `https://felica-auth.nyaa.ws`)

## Requirements
- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/)
- FeliCa reader/writer supported by nfcpy (e.g., Sony RC-S380)
- A libusb-compatible driver bound to the reader — see [Reader Driver Setup](#reader-driver-setup)
- Internet connectivity for communicating with the remote authentication server

## Installation

### Prebuilt executables
Every release ships standalone executables for `suica-viewer` and `suica-viewer-gui`; no Python installation is required. Download the file matching your platform from the [Releases](../../releases) page, alongside `SHA256SUMS.txt` to verify it.

| Platform | Asset suffix |
| --- | --- |
| Linux (x86_64) | `-linux-x86_64` |
| Windows (x86_64) | `-windows-x86_64.exe` |
| macOS (Apple Silicon) | `-macos-arm64` |
| macOS (Intel) | `-macos-x86_64` |

The macOS builds are unsigned, so Gatekeeper blocks the first launch. Allow the executable under System Settings → Privacy & Security.

You still need to set up the reader driver, and on Linux and macOS you still need libusb. See [Reader Driver Setup](#reader-driver-setup).

### From source

```bash
uv sync
```

## Reader Driver Setup
nfcpy talks to the reader through libusb, which needs a driver it can claim the USB device with.

**Windows.** libusb itself is bundled, but Windows binds its own driver to the reader by default and libusb cannot open it. Use [Zadig](https://zadig.akeo.ie/) to replace the reader's driver with **WinUSB**. Note that this makes the reader unavailable to the vendor's own software (for example Sony's NFC Port Software) until you restore the original driver from Device Manager.

**Linux.** Install libusb, then allow your user to access the device:

```bash
sudo apt install libusb-1.0-0

# Example udev rule for the Sony RC-S380 (0x054c:0x06c1, 0x054c:0x06c3)
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="06c3", GROUP="plugdev", MODE="0664"' \
  | sudo tee /etc/udev/rules.d/60-suica-viewer.rules
sudo udevadm control --reload-rules
```

Without the rule you have to run the tool as root.

**macOS.** Install libusb:

```bash
brew install libusb
```

## Usage (CLI)
1. Connect a compatible FeliCa reader to your PC.
2. Set `AUTH_SERVER_URL` if you need to specify a remote server.
3. Present the card while running the command below to output detailed information to the console.

```bash
uv run suica-viewer
# Example:
# AUTH_SERVER_URL=https://example.com uv run suica-viewer
```

Output is formatted with a balance summary up top, ANSI colors, and aligned tables (color is disabled automatically when not writing to a TTY or when `NO_COLOR` is set).

Options
- `--json` — emit JSON instead of the human-readable tables (for scripting)
- `-v`, `--verbose` — also show detail fields such as device numbers and raw codes
- `--no-color` — disable ANSI color
- `--server URL` — auth server URL (takes precedence over `AUTH_SERVER_URL`)

Main output items
- System issuance information (IDi, PMi)
- Issuance information 1 & 2 (issuer, issuing station, expiration date, etc.)
- Attribute information (card type, balance, transaction counter)
- Transaction history (parses gate entries/exits, purchases, charges; also shows the per-transaction balance change)
- Commuter pass data, gate entry/exit records, SF gate entry information
- Paid-ticket / express-gate records (料金発券・改札情報) — probed and read automatically only when the card carries them (service `0x1848`); cards without it, or an auth server lacking that key, are skipped gracefully without affecting the rest

## Usage (GUI)
```bash
uv run suica-viewer-gui
```

The GUI provides:
- Automatically polls the NFC reader after launch and displays progress while reading when a card is detected
- Overview tab led by a hero card showing the balance prominently, followed by key fields
- Light/Dark theme toggle in the top-right corner
- History tab displaying transaction history in a table, with a per-transaction balance-change column (charges highlighted in green), column-header sorting, and full-text filtering via the input box (`Ctrl+F` / `Cmd+F` to focus)
- Gates tab showing gate history, device numbers, amounts, commuter sections (sortable columns), SF gate entry data, and paid-ticket / express-gate records when present
- Data tab for viewing the card information JSON — copy to clipboard, save to a file, or export the transaction history as CSV

## Usage (Web GUI)
A browser cannot access the USB reader or run the authentication relay itself, so `suica-viewer-web` starts a small local server that owns the reader and streams card data to the page over Server-Sent Events.

```bash
uv run suica-viewer-web
# opens http://127.0.0.1:8765/ in your browser
```

- Auto-detects cards and updates the page live (no reload); mirrors the desktop GUI (hero balance, tabbed layout, sortable history with per-transaction deltas, gate table, JSON/CSV export, light/dark theme).
- Bound to `127.0.0.1` by default. Passing `--host 0.0.0.0` exposes card reading to your LAN — note that sensitive card data would then travel over the network.

Options:

| Flag | Description |
| --- | --- |
| `--host` / `--port` | Bind address (default `127.0.0.1:8765`) |
| `--server URL` | Auth server URL (overrides `AUTH_SERVER_URL`) |
| `--no-browser` | Do not open a browser on startup |
| `--demo` | Preview the UI with a built-in sample card (no reader required) |

The web GUI runs from source or an installed wheel (`uv run` / `pip install`); the prebuilt single-file executables cover the CLI and desktop GUI only.

## Authentication Server Configuration
- Default: `https://felica-auth.nyaa.ws`
- Set the base URL via the `AUTH_SERVER_URL` environment variable to switch servers (no trailing slash required).
- The server must provide the following endpoints:
  - `POST /mutual-authentication`
  - `POST /encryption-exchange`
- During mutual authentication, commands and responses are relayed to the card. Sensitive data such as personal information or card identifiers may be transmitted, so only connect to trusted environments.

## Station Code Data
- `suica_viewer/station_codes.csv` contains JR East and other station codes, allowing the app to resolve company, line, and station names from the line code and station index.
- Replace the CSV to use a custom dataset if necessary.

## Troubleshooting
- `LIBUSB_ERROR_NOT_SUPPORTED [-12]`: libusb found the reader but cannot open it because no libusb-compatible driver is bound to it. On Windows, install the WinUSB driver with Zadig as described in [Reader Driver Setup](#reader-driver-setup). Running as administrator does not help — that would report `LIBUSB_ERROR_ACCESS` instead.
- `LIBUSB_ERROR_ACCESS [-3]` on Linux: your user cannot access the USB device. Add the udev rule above, or run as root.
- `No such device` / `Unable to initialize NFC reader`: the reader is not plugged in, or nfcpy does not recognize its USB vendor/product ID.
- Frequent `Server communication error`: check the authentication server URL and your network connection. Adjust `AUTH_SERVER_URL` if needed.
- Message `Detected a non-FeliCa tag`: make sure you are presenting a supported card.

## Notes for Development
- Code formatting: `uv run black suica_viewer`
- The GUI does not support hot reload; restart the app after UI changes.
- Build artifacts such as `__pycache__` are not included in the repository; clean them up manually when needed.

### Building the executables locally
```bash
uv sync --group build
uv run pyinstaller packaging/suica-viewer.spec
```

The executables land in `dist/`. Build with an interpreter whose Tcl/Tk libraries the linker can resolve: uv's managed CPython ships Tcl/Tk 9, whose shared libraries PyInstaller cannot collect, which would yield a GUI binary that crashes on `import tkinter`. The spec fails the build rather than let that ship. Releases are built on CI with `actions/setup-python` for this reason.

Pushing a `v*` tag runs [`.github/workflows/release.yml`](.github/workflows/release.yml), which builds every platform and attaches the executables to the GitHub release.

## Author

- KIRISHIKI Yudai

## License

[MIT](https://opensource.org/licenses/MIT)

Copyright (c) 2025 KIRISHIKI Yudai
