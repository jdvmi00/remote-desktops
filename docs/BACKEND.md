# Running the backend from source

This development backend targets Linux/Omarchy. It requires Python 3, Moonlight
Qt, and a graphical user session to show remote windows. Hyprland window control
uses its current Lua dispatch and stable window IDs, without any Hypertile Lua
module. The Rust toolchain is pinned in `rust-toolchain.toml`.

Omarchy ships a Moonlight rule that requests fullscreen even with
`--display-mode windowed`. The backend now clears fullscreen once on the first
matched window of a new stream. Later user fullscreen choices are preserved.
See [launchers](LAUNCHERS.md) for identity and startup details.

## Configuration

Create `~/.config/remote-desktops/computers.json` using
[the synthetic example](computers.example.json). XDG config, state, and runtime
directories are respected. Runtime files live under
`$XDG_RUNTIME_DIR/remote-desktops`; session and recovery files live under
`$XDG_STATE_HOME/remote-desktops` (default `~/.local/state/remote-desktops`).

Pair the host using Moonlight first. Read its UUID from Moonlight's own
configuration and put that identity in `pairing_uuid`. Certificates stay with
Moonlight. Set `title` to the final remote window title. Configure Sunshine to
offer the `Desktop` app, with the required capture/input permissions.

Use `--profile NAME` to select a profile. Otherwise `default_profile`, then a
profile named `desktop`, then the first profile in sorted order is selected.
Opening an already-connected profile reuses its client; changing profiles
requires disconnect and completed recovery first.

An `external` display profile leaves host display settings alone. The `macos`
adapter follows the main Mac display without changing its mode; it requires an
approved noninteractive SSH user. The optional `betterdisplay` adapter can
manage a physical display's mode and requires its UUID and advertised mode.
The `windows` adapter uses an already-installed console-session recovery helper,
an approved `ssh.alias`, and persistent `display.device_id`. These retain the
configuration rules and recovery behavior from the extracted host adapters.

New Windows computers default to `sunshine` and a saved 1920x1080 stream.
This adapter requests resolution changes through Moonlight's game-optimization
flag without SSH. Sunshine must have display configuration enabled and
`dd_resolution_option = auto` on the host. Refit requests the current window
size and remembers it. Host resolution remains unverified: unsupported modes
may leave the host at an existing size with scaled video, or capture may fail.
Other platforms default to `external`; existing profiles are preserved.

The optional `virtual` adapter (Windows, shown as Verified matching (SSH))
adds read-only SSH verification. Set `display.output` to the Sunshine display
GUID selected during inspection and configure Sunshine's `output_name` to it.
The same automatic resolution configuration is required.

For verified matching, each launch records the Sunshine log position before starting Moonlight. Bounded
new log output must identify the selected output and confirm the requested host
resolution. A missing display, wrong resolution, rotated log, or verification
timeout is an error; fallback capture is not accepted as successful matching.
Raw host logs are not persisted. The current reader retains its launch cursor
and rereads up to 131,072 bytes and 65,536 characters. A long or noisy session
can exceed this bound and fail closed with `display-verification-lost`; reconnect
to establish a new observation. Incremental log parsing is not implemented. The reported host resolution is launch-scoped
Sunshine evidence, not an independent measurement of every subsequent display
change. Unsupported log formats remain unverified. In this verified mode, Refit is enabled only for
`stream_resolution = auto` sessions with recent verified host evidence, and the
CLI rechecks before restarting.

Driver-specific mode management is separately opt-in: `display.sync_modes = true`
adds the stream size to `display.settings` (default
`C:\VirtualDisplayDriver\vdd_settings.xml`) over SSH and requests a driver reload.
Leave this off for physical monitors and drivers with host-managed modes. The XML
list alone never verifies the active modes or a successful capture. Existing
size/refresh entries are preserved, and additions persist after disconnect;
Sunshine restores the active display, not this XML configuration. A failed reload
is reported and retried on the next sync, even when the requested entry already
exists. Adjacent `.remote-desktops.lock` and `.remote-desktops.reload-pending`
files serialize app edits and retain unfinished reload intent. No reload is requested for an unchanged list after a successful sync. Existing
profiles are not migrated; old `virtual` profiles need their capture output
selected in setup before their next connection.

A profile's `stream_resolution` is either `WIDTHxHEIGHT` or `auto`. With
`auto` or the `sunshine` adapter the daemon launches at the last known size for the window: the size last
fitted for that monitor and workspace, or `display.initial_resolution` (falling back to the saved stream resolution, then 1920x1080) the first time.
A connect never restarts to fit. `refit COMPUTER`, or `refit` for the focused
Moonlight window, is the only thing that matches the stream to the window: it
restarts once at the window's current size, remembers it, and returns the window
to the workspace it was on. Sunshine profiles can connect without Hyprland using the saved initial or
default size, including when set to `auto`. Explicit Refit requires an owned
window. For other adapters, `auto` needs Hyprland; elsewhere the connection fails
with `fit-unavailable`. Status reports the size in use as `resolution` with
`fit_window`.

Never store passwords, private keys, or pairing certificates in this file.

The graphical manager can set up the managed adapters. For a Mac it needs the
approved SSH user and, for BetterDisplay, a display and mode read from the Mac
over SSH. For Windows it needs an SSH alias that reaches an administrator
account, a virtual display already captured by Sunshine (`output_name`), and
the console helper, which it installs over that alias. These fields are the
only SSH and display settings the manager edits; keys, known hosts, and
certificates stay where they are.

## Commands

```sh
cargo build --locked --release
./target/release/remote-desktops computers
./target/release/remote-desktops connect macbook --profile desktop
./target/release/remote-desktops status macbook --json
./target/release/remote-desktops focus macbook
./target/release/remote-desktops reconnect macbook
./target/release/remote-desktops disconnect macbook
./target/release/remote-desktops restore macbook
./target/release/remote-desktops start
./target/release/remote-desktops settings remove macbook
./target/release/remote-desktops window-rule install   # Moonlight windows open tiled
./target/release/remote-desktops refit macbook        # refit an auto stream to its window now
./target/release/remote-desktops refit                # refit the focused Moonlight window
./target/release/remote-desktops settings discover
echo '{"host":"garage.example.net","pin":"1234"}' | ./target/release/remote-desktops --json settings pair
```

`settings discover` lists computers seen on Tailscale (`tailscale status`) and
announcing Sunshine on the local network (`avahi-browse`), merged by name, with
their platform, reachability, and whether Moonlight has already paired them.
Both tools are optional; a missing or failing tool yields an empty list.

`settings pair` runs Moonlight's own `moonlight pair HOST --pin PIN` and waits
up to two minutes for the PIN to be entered in Sunshine's web interface on the
host. Certificates and the client identity stay in Moonlight's configuration;
the command reads the new host back from there. It refuses while the Moonlight
window is open, because Moonlight rewrites that configuration on exit.

`settings inspect` reads a host's displays over the approved SSH access for a
JSON draft on stdin: on a Mac, every active display with its modes and power
state; on Windows, the displays, Sunshine's `output_name`, and whether the
console helper is installed. `settings install-helper` installs the Windows
helper for a draft that names the capture display. Neither changes a display.

`start` starts the daemon if it is not running and reports status without
connecting anything. `settings remove` deletes a computer's configuration and
its generated launcher entry, and forgets its session record only when nothing
owns it: it refuses while the session is desired, a client is alive, the
session is still finishing, or a recovery journal is pending. With the daemon
running, the record is dropped through the daemon's `forget` command;
otherwise the CLI holds the daemon's writer lock while deleting the directory.
A computer removed this way can be added again from the same pairing.

Connect/disconnect/restore/reconnect start the daemon on demand. To run it in
the foreground for development, use `remote-desktops daemon`. A CLI command
returning successfully means the intent was accepted; inspect `status` for
`preflight`, `preparing`, `connecting`, `running`, `window-ready`, `stopping`,
`restore-pending`, `idle`, or `attention`.

`running` means an owned client process exists. `window-ready` additionally
means its final window was observed. Neither guarantees a decoded video frame.
Closing the remote window ends its session and triggers host restoration.
Reconnect keeps the recovery baseline while replacing the client.

If restoration conflicts with a manual host change, that change is preserved
and the journal stays pending. Use `restore` to retry. Only when intentionally
keeping the host settings, acknowledge their release with:

```sh
./target/release/remote-desktops release macbook --keep-host-settings
```

Stopping/crashing the daemon does not kill supervised clients. Starting the
daemon again adopts them and resumes pending recovery. Until packaging adds
service restart integration, run/start the daemon again after a crash; a saved
journal alone cannot execute local macOS recovery while the daemon is stopped.
The Windows console helper retains its independent offline recovery behavior.

## Handoff and installation

Do not start this backend against your current computers while Hypertile's
stream controller is active. Finish/disconnect the old sessions and resolve
their recovery journals before an explicitly planned handoff. The new daemon
refuses an active legacy controller and refuses matching outstanding legacy
session/recovery intent. It never adopts old journal files automatically.

Desktop entries can be installed explicitly with `launcher install COMPUTER`.
No package installer or automatic live migration is included. Run the binary
from its checkout so it can find the Python helper package. A future package
can supply the helper root using `REMOTE_DESKTOPS_HELPERS`; this is a local
development/package setting, not a remote host option.

Automated tests do not install the application or change hosts. Separately
authorized live MacBook validation is recorded in [validation](VALIDATION.md);
real Windows streaming remains untested by this application.
