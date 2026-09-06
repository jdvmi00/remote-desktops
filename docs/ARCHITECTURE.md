# Architecture and performance

## Stack decision

The local daemon, CLI, and client supervisor use Rust with Tokio. Moonlight Qt
remains a separate client process; Sunshine remains the remote server. The
planned graphical manager uses Qt 6/QML in a separate process, communicating
over the daemon's Unix socket. The backend has no Qt dependency. No GUI or Qt
bridge is implemented in this feature.

The existing Python macOS adapter and Windows transport/recovery algorithms are
kept behind a one-operation helper interface. Windows retains its PowerShell
console-session helper and native C# display calls. Rewriting these algorithms
alongside extraction would create recovery risk without improving video latency.
The helper starts only for configuration, host operations, or active-session
health checks; there is no continuously running Python controller.

Rust was selected for bounded process/socket handling and low resident overhead,
not as a claim that a language change reduces streaming latency. Video frames,
audio, decoding, and input never pass through our daemon, helper, or manager UI.
Moonlight retains hardware decoding and its own rendering/frame pacing.

## Ownership and concurrency

- One daemon owns the user state directory under an exclusive writer lock.
- Each computer has one asynchronous worker. Host operations are serialized for
  that computer, while other computers and status/disconnect requests continue.
- Session intent and recovery use separate files. Rust writes `session.json`;
  the Python helper alone writes `recovery.json` under an operation lock. Both
  use private atomic file replacement and fsync.
- Disconnect intent is durable immediately. An already-started host operation
  may finish, but its journal is retained and restored before any client launch.
  Cancelling a task must never erase an uncertain host write.
- A detached Rust supervisor launches each Moonlight process under a per-token
  lock and session gate. It verifies current intent before spawning, records the
  client PID, and signals job changes over a local datagram socket. Supervisors
  survive daemon restart; a restarted daemon adopts their token-owned processes.
- Process signals use Linux pidfds and token verification. Window actions
  recheck address, PID, stable identity, class, and title inside Hyprland before
  dispatching. A recycled address is not sufficient ownership evidence.
- A bounded parser retains only typed Moonlight 6.1 evidence. Raw client logs,
  URLs, credentials, and screen content are not persisted. Unknown client
  versions remain usable, with log-derived observations marked unsupported.

## Window behavior

Moonlight launches in windowed mode. The controller never creates workspace
rules, reserves tiles, changes geometry, or repairs a user's placement. Window
creation, title, visibility, and movement are observed through Hyprland events;
event bursts are coalesced before a snapshot query. Visibility can update idle
inhibition on the owned window. Explicit focus/reconnect/disconnect can focus
or close an owned window, but reconciliation never moves it.

The CLI also runs without a Hyprland observer. In that case it reports process
state (`running`), with no window identity or focus control. `window-ready` is
evidence of a matched window, not a measured first video frame.

## Performance bounds

- Two Tokio executor threads per daemon; no worker thread per configured host.
- Idle sessions wait for commands. Active sessions reconcile on process/window
  events, with a ten-second process fallback and host health observation.
  Compositor snapshots run on window events and observer reconnection.
- Only active managed displays receive host health checks, at ten-second
  intervals. External display profiles do not receive SSH health probes.
- Existing SSH configuration/control sockets can reuse authentication and
  connections; the app does not change SSH configuration automatically.
- State writes occur only when state changes. No per-frame file writes, JSON,
  Python execution, or GUI callbacks occur in the video path.
- IPC request/response sizes, client-log line sizes, operation durations, and
  network recovery attempts are bounded. Connection-loss code -100 permits
  three retries with 2/5/15-second backoff; unknown exits do not auto-retry.

Measure idle CPU, resident memory, CLI response time, launch-to-window time,
reconnect time, and actual video statistics separately. A mock-client test or
window-ready timestamp does not establish end-to-end latency. Host subprocess
cost and SSH latency remain measurable optimization candidates; replace a helper
only with evidence of a bottleneck and equivalent recovery tests.

## Separation from Hypertile

The daemon takes a shared lock on an existing legacy stream-controller lock;
Hypertile's controller needs the exclusive lock. Supervisors inherit the shared
lock, allowing a new Remote Desktops daemon to adopt them while keeping the old
controller out. A matching legacy desired session or pending recovery journal
blocks connection until explicit handoff. No legacy state is copied or rewritten.

The Windows mailbox directory and recovery task keep their existing Hypertile
names for protocol compatibility. These helpers are included here and do not
require the local Hypertile plugin. Do not install a second console helper or
discard an existing journal during migration.

Scenes and layout browsing remain in Hypertile. Generic application launch and
window matching in Scenes are a subsequent feature.
