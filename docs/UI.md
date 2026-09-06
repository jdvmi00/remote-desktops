# Desktop manager

The Qt 6/QML manager is a separate application for setting up and connecting computers. It
shows connection state, selects an existing profile, connects, focuses,
disconnects, reconnects, restores a pending host display, and installs a
per-computer application launcher. It has no video renderer and owns no host
recovery. Closing it leaves the daemon and Moonlight sessions running.

## Run from a checkout

Build the Rust backend using the repository toolchain, then the Qt manager:

```sh
cargo build --locked
cmake -S ui -B build/ui -DCMAKE_BUILD_TYPE=Release
cmake --build build/ui --parallel 2
build/ui/remote-desktops-manager --backend "$PWD/target/debug/remote-desktops"
```

The UI requires Qt 6.4 or later: Quick, Quick Controls 2, Network, and the Qt
Test development module for the test target. No Qt libraries are linked into
the Rust backend. The manager accepts an absolute backend path; otherwise it
looks beside itself and then on PATH. Configuration and socket paths follow
the backend's XDG conventions.

Opening the manager reads configured computers and status. It does not start a
connection automatically. An explicit Connect starts the daemon when necessary.
Do not use a development binary to take over active production sessions merely
to test the UI. Use the isolated preview instead:

```sh
build/ui/remote-desktops-manager --demo
build/ui/remote-desktops-manager --demo --state restore-pending
ctest --test-dir build/ui --output-on-failure
```

Demo actions never spawn the backend or access its socket. The three example
computers are synthetic. `--state` also supports `idle`, `preflight`, `empty`,
and `unavailable`; `--compact` exercises the minimum window size. With an
offscreen platform, `--screenshot /tmp/manager.png` exports the rendered demo.
These preview and screenshot options require `--demo`.

## Interaction design

- A stable computer list sits beside the selected connection. Selection is
  retained by computer ID, rather than by a changing row index.
- One primary action follows state: Connect, Open desktop, or Restore display.
  Repeat actions are suppressed while an acknowledgement is pending. A request
  acknowledgement is not presented as a successful connection.
- Profiles cannot change during a desired session; disconnect first. Reconnect
  restarts the selected client. Disconnect cancels pending connection intent
  and asks the daemon to restore its owned host settings.
- Host recovery errors remain visible, with technical detail available on
  demand. Recovery records for removed computers remain in the list. There is
  deliberately no one-click abandonment of the original host settings.
- Status loss preserves last-known records and labels them unavailable; it
  does not pretend that a running remote session disconnected. Refresh retries
  observation. Connect/Restore use the CLI's existing daemon-start behavior.
- No thumbnails or performance figures are invented. The device drawing is an
  illustration. Window-ready is an identity match, not proof of a rendered
  video frame or measured latency.
- Tab navigates controls, arrow keys navigate the focused computer list,
  Ctrl+Enter invokes the primary action, Ctrl+R refreshes, and Escape closes
  a dialog. Focus rings, accessible names, textual statuses, and restrained
  hover transitions complement color cues.

## Current scope

Choose **Add computer** to select a computer already paired in Moonlight,
confirm its name and address, choose desktop quality, then test and save. The
check authenticates through Moonlight and verifies the Desktop app is listed.
It does not start video, capture input, or change a host display. Pairing and
certificate storage stay in Moonlight. If no paired computers appear, complete
pairing there and refresh the setup list.

New profiles use the host’s existing display and automatic decoder selection.
Advanced controls expose resolution, frame rate, bitrate, codec, mouse mode,
and audio policy. **Edit** changes an existing computer and its default profile;
other profiles, SSH configuration, host display adapters, and window identity
are preserved. Changes apply after disconnecting and starting a new connection;
Reconnect continues using the active session’s snapshot.

The save button requires a successful check of the current draft. Editing any
field invalidates that check. Validation or reachability failures leave the
saved configuration untouched. A revision conflict asks you to reopen setup,
so another editor’s changes are not silently overwritten. Cancel discards the
draft. Saving and optional launcher installation are separate operations: a
launcher failure leaves the computer saved and can be retried from the main
screen. Existing launcher entries can be updated from the final setup step.

Use `--demo --setup-preview computer` (or `preferences`, `advanced`, `check`)
to preview each setup page with synthetic data. Demo settings stay in memory.

The manager does not install itself, register a system service, migrate legacy
configuration, or change Hypertile. Packaging remains a separate delivery step.

## Omarchy themes

The manager automatically reads the active Omarchy palette from
`$XDG_STATE_HOME/omarchy/current/theme/colors.toml` (normally
`~/.local/state/omarchy/current/theme/colors.toml`). Background, foreground,
accent, surfaces, and warning/destructive colors follow that theme. Derived
colors support light and dark palettes, with contrast-adjusted text for
buttons and recovery messages.

Filesystem notifications update the palette without restarting the manager or
its connections, including when Omarchy replaces the entire theme directory.
There are no installed hooks, theme-file writes, subprocesses, or periodic
palette polling. Outside Omarchy, a built-in palette is used. Partial, malformed,
or temporarily missing theme files retain the last complete palette.

For isolated visual checks, pass `--theme-file /path/to/colors.toml`; the light
fixture is `ui/tests/light.toml`. The reader accepts flat quoted `#RRGGBB` color
assignments and ignores non-color metadata. It never executes theme code.
