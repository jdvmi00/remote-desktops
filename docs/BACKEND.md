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
