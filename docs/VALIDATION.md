# Backend validation

## Local checks

The initial Rust backend passed format and Clippy checks, five Rust unit tests,
29 Python repository/host recovery tests, and 13 integration tests using the
real daemon, CLI, and supervisor with isolated fake clients and host operations.
Both debug and optimized release builds succeeded.

The integration cases cover simultaneous connects, multiple computers,
cancellation during preparation, daemon restart during preparation and streaming,
client close/crash, reconnect, recovery conflicts and malformed journals, legacy
ownership conflicts, oversized IPC requests, and workspace/geometry changes.

The Windows PowerShell policy suite requires its native GitHub runner. Local
Linux results do not stand in for that required check.

## Initial overhead measurement

Measured on the development machine on 2026-09-05, Linux
`7.1.9-arch1-2-x86_64`, glibc 2.44, Rust 1.98.1, optimized release build:

| Metric | Observed value |
| --- | --- |
| Stripped executable | 1,629,688 bytes |
| Empty daemon resident memory | 3,968 KiB |
| Idle CPU time over three seconds | 0 observed ticks (10 ms tick resolution) |
| Status socket round trip, median of 100 requests | 0.046 ms |
| Status socket round trip, 95th percentile | 0.071 ms |

Reproduce with:

```sh
cargo build --release --locked
REMOTE_DESKTOPS_BIN=target/release/remote-desktops python3 tests/benchmark.py
```

This is a small local sample of an empty daemon with no compositor observer or
active clients. Socket timing includes a new connection and JSON response per
request, but excludes CLI process startup. Measurements vary by machine and
load; they are not CI performance thresholds or streaming latency claims.

No real Mac/Windows host, Sunshine connection, decoder, audio path, or input
latency was exercised. Measure active-session memory/CPU, compositor activity,
host health checks, startup/reconnect time, and Moonlight video statistics during
the separately planned live handoff. GUI overhead remains unmeasured because
the Qt manager is a subsequent feature.

## Live MacBook validation

On 2026-09-05, the owner authorized a temporary handoff from the idle Hypertile
stream controller. The original configuration remained intact. Only the MacBook
profile was copied into the local app configuration; no private profile,
pairing material, runtime state, or screenshot was added to this repository.

Environment: Hyprland 0.56.2, Moonlight Qt 6.1.0, the native `macos` display
adapter, and a MacBook with its lid closed. Results:

- Moonlight authenticated the paired host and opened Desktop. Negotiated video
  was 2560x1440 at 60 fps, and the Mac desktop was visually observed.
- Restarting the daemon preserved and adopted the same live Moonlight process.
- The live focus check found a JSON/Lua window identity mismatch. Hyprland JSON
  supplies hexadecimal stable IDs; its Lua API uses numeric IDs. The backend now
  converts the ID before checking ownership. A regression test covers this
  representation difference, and focus succeeded against the real window.
- After leaving Omarchy's default Moonlight fullscreen mode, the window moved
  from workspace 1 to an empty workspace 3. It stayed there for twelve seconds
  with the same client PID and session generation. Floating resize to 1600x900
  preserved the client and negotiated video resolution; the window was then
  returned to its original workspace.
- Explicit reconnect reached a new matched window in approximately 12.64
  seconds in one observation. It preserved the recovery journal, and opening
  the target again reused that client. Exactly one matching window remained.
- Both a clean client close and explicit disconnect completed recovery. Remote
  readback matched the original Sunshine output selection and unchanged
  1920x1080, 60 Hz display mode. This adapter preserves display mode; this does
  not test changing and restoring a BetterDisplay-managed mode.
- The final session was idle with an empty recovery journal. The standalone
  daemon was stopped and the original Hypertile controller restarted, with no
  remote windows remaining.

The desktop's default fullscreen rule remains a launcher/packaging integration
item. Keyboard/mouse usability, audio, sustained frame delivery, and end-to-end
latency were not independently verified. Windows live streaming and recovery
still require separate host validation. These observations supplement the
isolated regression suite; they do not turn mock performance samples into
streaming performance measurements.
