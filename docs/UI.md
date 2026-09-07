# Desktop manager

The Qt 6/QML manager is a separate application for setting up and connecting
computers. It shows connection state, selects an existing profile, connects,
focuses, disconnects, reconnects, restores a pending host display, installs a
per-computer application launcher, and removes computers. It has no video
renderer and owns no host recovery. Closing it leaves the daemon and Moonlight
sessions running.

## Run from a checkout

Build the Rust backend using the repository toolchain, then the Qt manager:

```sh
cargo build --locked
cmake -S ui -B build/ui -DCMAKE_BUILD_TYPE=Release
cmake --build build/ui --parallel 2
build/ui/remote-desktops-manager --backend "$PWD/target/debug/remote-desktops"
```

The UI requires Qt 6.4 or later: Quick, Quick Controls 2, Network, the SVG
image format plugin for its icons, and the Qt Test development module for the
test target. No Qt libraries are linked into the Rust backend. The manager
accepts an absolute backend path; otherwise it looks beside itself and then on
PATH. Configuration and socket paths follow the backend's XDG conventions.

Opening the manager reads configured computers and status. It does not start a
connection automatically. An explicit Connect, or the Start service action shown
when the service is not answering, starts the daemon. Window size and the last
selected computer are kept in the application's QSettings file; the preview
never writes them. Do not use a development binary to take over active
production sessions merely to test the UI. Use the isolated preview instead:

```sh
build/ui/remote-desktops-manager --demo
build/ui/remote-desktops-manager --demo --state restore-pending
build/ui/remote-desktops-manager --demo --state many --compact
build/ui/remote-desktops-manager --demo --dialog help
ctest --test-dir build/ui --output-on-failure
```

Demo actions never spawn the backend or access its socket; they walk through
the same intermediate phases a real session reports. The example computers are
synthetic. `--state` supports `idle`, `connecting`, `preflight`, `running`,
`attention`, `restore-pending`, `empty`, `unavailable`, `many` (twelve
computers), and `unconfigured` (a removed computer with a pending restore).
`--dialog` opens `help`, `preferences`, `details`, `remove`, `notice`, or `error`.
`--setup-preview` accepts `computer`, `pair`, `preferences`, `recovery`
(macOS with BetterDisplay), `windows`, `matching` (verified Windows matching),
`advanced`, and `check`. `--compact`
renders the minimum window size. With an offscreen platform,
`--screenshot /tmp/manager.png` exports the rendered demo. These preview and
screenshot options require `--demo`.

## Local development loop

Use `python3 scripts/dev.py build` to build the Rust CLI/daemon and Qt manager
in the checkout. Rust/Cargo and the Qt dependencies listed above must be on
PATH. This command does not install files or restart running processes.

For UI work without a real host:

```sh
python3 scripts/dev.py preview
python3 scripts/dev.py preview --setup-preview windows
```

For live testing, first disconnect all streams in the existing manager and
finish any pending display recovery. Close that manager, then stop its daemon
with SIGTERM (or stop its service if you configured one). Confirm the PID before
signalling it; the `ui` command below reports a conflicting daemon's PID.
Do not delete state or recovery files. Start these in separate terminals:

```sh
python3 scripts/dev.py daemon
python3 scripts/dev.py ui
```

These use your existing configuration and state. The daemon runs in the
foreground and uses the checkout's Python/PowerShell helpers. Its existing
writer lock prevents a second controller from taking ownership. The UI command
checks the socket's peer PID against the current build's executable inode and
refuses an installed or outdated daemon. Use this command instead of the desktop
launcher during development. CLI actions are available through, for example,
`python3 scripts/dev.py cli status`.

After editing:

- Python and PowerShell helpers are read from the checkout on the next host
  operation. Reconnect or Refit explicitly to exercise launch-time changes.
- QML/C++ changes: run `python3 scripts/dev.py build`, close the dev manager,
  and reopen it with `ui` (or `preview`). QML is embedded in the executable;
  there is no automatic hot reload.
- Rust changes: disconnect streams and finish recovery, close the dev manager,
  stop the foreground daemon with Ctrl+C, build, then run `daemon` and `ui`
  again. Rebuilding alone does not replace a running daemon or supervisor.

Closing a manager or pressing Ctrl+C in the daemon does not disconnect streams
or restore displays. Always disconnect through the app before stopping the dev
daemon. Builds and previews are separate from the full checks in
[the development workflow](RELEASING.md); real streaming remains a manual test.

## Layout

- The header carries the application identity, the background service
  indicator (running, not responding, or starting; click it to check again),
  refresh, preferences, and help. Preferences holds one desktop option: Open
  remote desktops tiled, which adds or removes the Hyprland rule described in
  LAUNCHERS.md and explains when a hand-written rule already covers it.
- The sidebar lists computers with a status dot and label per row, scrolls
  with a visible bar, and holds the one global primary action, Add computer.
- The main pane shows the selected computer's name, platform, and address,
  then a status card, the action row, the profile, and tertiary actions (Edit,
  Add to or Remove from app launcher, Details, Remove). The launcher action
  reflects whether the desktop entry currently exists. Nothing else competes
  for the space.
- When the service is not answering, one banner names the cause and offers
  Start service and Check again. Rows keep their last known label with a
  hollow dot, and the card says which state was last known.
- Transient messages appear as a toast over the main pane. Informational
  messages fade after five seconds; errors stay until dismissed or replaced.
  Accepted connection commands produce no message because status shows them.

## Status card

The card states what is happening, what it means, and what to do next, with a
tone that follows the state: neutral, connected, or warning. It lists only
values the daemon reports: time since the client launched, the profile,
whether an owned window was detected, the negotiated video size and rate from
Moonlight's own log, the Moonlight version, the next retry with its attempt
count, and the last error message inline. Nothing is invented: no thumbnails,
latency, or quality figures. Window detection is an identity match, not proof
of a rendered frame.

## Interaction design

- Selection is retained by computer ID rather than a row index. Tab reaches
  the list; Up, Down, Home, and End move through it; typing a letter jumps to
  the next matching name; Enter or a double-click runs the primary action.
  Ctrl+Enter runs the primary action, Ctrl+R refreshes, Ctrl+N adds a
  computer, and Escape closes a dialog.
- One primary action follows state: Connect, Open desktop, or Restore display.
  While a transition runs, the primary action is disabled and labeled with the
  phase, and Cancel sits beside it, never in the position Disconnect uses. A
  running client without an observed window disables Open desktop; Reconnect
  and Disconnect remain. Repeat actions are suppressed while a request is
  pending. A request acknowledgement is not presented as a connection.
- Profiles cannot change during a desired session; disconnect first. A
  computer with a single profile shows it as text rather than a control.
- Host recovery errors stay visible inline in the card, with a details dialog
  for identity, state, window, client, and copyable text. Recovery records for
  removed computers remain listed until restored. There is deliberately no
  one-click abandonment of the original host settings.
- Remove asks for confirmation, then calls `settings remove`. The backend
  refuses while the computer is connected, still finishing a session, or has
  a pending display restore, and the reason is shown as an error message.
- Focus rings, accessible names and roles, textual statuses, and restrained
  animation on state changes complement color cues.

## Guided setup

Choose **Add computer**. The first step lists computers already paired in
Moonlight, and below them the computers found through Tailscale and on the
local network, each with its platform, whether it is online, and whether it is
already paired. Picking an unpaired computer, or entering an address by hand,
opens the pairing page: a four-digit PIN, the address of Sunshine's web
interface on that host, and a progress line while Moonlight waits. Pairing
runs through Moonlight's own command line, so certificates stay in Moonlight;
the dialog asks you to close the Moonlight window first. A rejected PIN offers
a retry with a new one. A successful pairing continues to Settings with the
name, address, and platform already filled in.

Steps are shown with completed, current, and upcoming markers; editing an
existing computer skips the first step and shows two.

For a macOS or Windows computer the Settings step adds **Display recovery**.
New Windows computers default to Match via Sunshine (no SSH) and a saved
1920x1080 stream. Sunshine must have display configuration enabled and automatic
resolution switching set to `auto` on the host. Refit requests the window size
and remembers it; resizing alone scales the picture. Host resolution is shown
as unverified. An unsupported mode may result in scaled video at an existing
host resolution or a connection failure. Existing profiles are preserved.

Verified matching (SSH) is optional. Inspect the PC pins Sunshine's configured
output. Refit in this mode requires recent evidence of the selected output and
requested host resolution. Missing displays and mismatched captures report an
error. Managing Virtual Display Driver sizes is a separate unchecked option. It adds
missing size/refresh combinations persistently, preserves existing entries, and
requires a successful driver reload. Display restoration does not remove these
added configuration entries.
Other platforms default to Use existing host display. Mac display management
and Windows console recovery retain their existing SSH requirements.

Continue validates the name, address, and resolution and shows the rule under
each field that needs attention. The check runs automatically when the last
step opens and can be repeated with Check again. It authenticates through
Moonlight and verifies the Desktop app is listed; it does not start video,
capture input, or change a host display. A revision conflict offers Reload,
which refreshes the saved revision for a new computer or reloads the saved
settings for an existing one. The summary lists name, address, operating
system, quality, mouse, and audio in plain language. Save requires a passing
check of the current draft; editing any field invalidates it. Escape or Cancel
with unsaved changes asks before discarding.

New Windows profiles request display matching through Sunshine; other platforms
use the host's existing display. All new profiles use automatic decoder selection.
Advanced controls expose resolution, frame rate, bitrate in Mbit/s, codec,
mouse mode (direct or relative pointer), and audio (play here and mute when
unfocused, always play here, or play here and on the host), each with a one-line
explanation. Host playback does not mute local playback. Audio changes apply
after Disconnect followed by Connect; Reconnect retains the current session
settings. The resolution field is a combo box: pick a size from the list or
type any WIDTHxHEIGHT, since Moonlight streams at whatever size is requested
and Sunshine scales the captured display to match. The list starts with what
the host was seen to offer, then common sizes: the modes of a display managed
with BetterDisplay (HiDPI modes also appear at their doubled pixel size), the
Mac's current main display mode, or the capture display's size on Windows.
Enable manual Refit opens each connection at its last remembered stream size.
Refit explicitly restarts at the current window size. Verified matching also
checks host capture afterwards. The connection view labels requested stream size, negotiated
video size, and verified host display size separately. Verified matching currently rereads a bounded log segment from launch: more
than 128 KiB or 65,536 characters revokes verification and requires reconnecting,
so a long or noisy session can hit this limit. Host display size is
shown as Host resolution unverified without recent launch-scoped Sunshine evidence; a client
stream size alone never earns a “fits the window” label.

Use `--demo --setup-preview computer` (or `preferences`, `advanced`, `check`)
to preview each setup page with synthetic data. Demo settings stay in memory.

The manager does not install itself, register a system service, migrate legacy
configuration, or change Hypertile. Packaging remains a separate delivery step.

## Omarchy themes and type

The manager automatically reads the active Omarchy palette from
`$XDG_STATE_HOME/omarchy/current/theme/colors.toml` (normally
`~/.local/state/omarchy/current/theme/colors.toml`). It uses `mode`,
`background`, `foreground`, `accent`, `lighter_background`,
`dark_background`, `selection`, `muted`, `red`, `yellow`, and `green`; only
the first three are required. Every shared foreground, including disabled
text and status colors, is adjusted until it reads at WCAG AA contrast on
every surface it is drawn on, in light and dark palettes alike.

Text uses the desktop's application font as provided by the platform theme;
no family is hardcoded. A five-step type scale is derived from that font's
size, with the smallest step never below nine points.

Filesystem notifications update the palette without restarting the manager or
its connections, including when Omarchy replaces the entire theme directory.
There are no installed hooks, theme-file writes, or periodic palette polling.
Outside Omarchy, a built-in palette is used. Partial, malformed, or
temporarily missing theme files retain the last complete palette.

For isolated visual checks, pass `--theme-file /path/to/colors.toml`; the light
fixture is `ui/tests/light.toml`. The reader accepts flat quoted `#RRGGBB` color
assignments and the `mode` key and ignores other metadata. It never executes
theme code.
