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
