# Desktop manager

The Qt 6/QML manager is a separate application for configured computers. It
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

This first manager manages existing configuration. Pairing still happens in
Moonlight; adding/editing computer and profile configuration follows the
[backend setup guide](BACKEND.md). The in-app help explains that flow. A guided
pairing/configuration editor is subsequent work; this UI does not offer a
placeholder form or write unvalidated settings.

The manager does not install itself, register a system service, migrate legacy
configuration, or change Hypertile. Packaging and a graphical setup wizard are
separate delivery steps.
