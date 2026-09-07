# Repository audit — 2026-09-07

The audit covered the working implementation, including the previously
uncommitted audio, setup, developer tooling, and display-matching work committed
as `46e3168`. Three independent agents reviewed feature usability/UI, Rust
architecture/lifecycle, and Python/Windows host operations. The coordinating
agent reviewed documentation, window-rule editing, test coverage, and rendered
UI output. A fourth agent independently verified their findings before fixes
and reviewed the resulting patch for regressions.

The central architecture remains appropriate: Rust owns the daemon, CLI, and
supervision; Python owns bounded host operations and recovery; Qt is a separate
manager; Moonlight/Sunshine own media and input. No language or framework rewrite
was recommended. The audit found concrete ownership, configuration-preservation,
and error-reporting bugs within those boundaries.

## Verified findings and implemented changes

| Priority | Finding | Change and evidence |
| --- | --- | --- |
| High | Session removal could delete a helper-owned directory or race a new connection. Offline removal lacked live-process checks. | Online/offline removal now share recovery/launch ownership checks and durable settled-state validation. Atomic retirement occurs under lifecycle ownership before map removal; cleanup cannot delete a replacement session. Integration tests cover held locks, live offline supervisors, and a failed retirement preserving visible state. |
| High | A PID-publication error after spawning could leave an untracked client running while recovery proceeded. | A child guard kills and reaps on post-spawn error. A Rust fault-injection test fails publication with a real isolated child and proves it was reaped. Abrupt supervisor death remains separately limited below. |
| High | An unterminated managed window-rule block consumed all following user configuration. | Malformed, nested, and unmatched markers now fail before configuration writes. Unit/integration tests cover malformed blocks, CRLF, absent final newline, and preservation of following content. |
| High | Optional virtual-mode synchronization deleted unrelated existing modes to keep eight entries. | Existing modes are preserved; only missing width/height/refresh combinations are appended. Native Windows fixtures contain more than eight preexisting modes. |
| Medium | Blocking launch-gate acquisition held the global session mutex and could stall unrelated requests. | Updates retry asynchronously outside the global mutex and revalidate session incarnation. Held-gate integration tests verify other status/disconnect requests continue and desired intent survives contention. |
| Medium | Fixed-size Sunshine connections failed without Hyprland. | Sunshine profiles fall back to their saved initial/default size. Explicit Refit requires a live owned window. Compositor-free integration coverage verifies launch size and unavailable Refit. |
| Medium | Window-rule reload/query errors falsely reported success. | Reload and verification failures are returned, with rollback when the file still equals the app's write. Detected external edits are preserved. Fake-compositor tests cover failed reload, failed query, new parse errors, and external edits during verification. |
| Medium | Driver reload failure was swallowed and never retried once the XML entry existed. | A flushed pending-intent sidecar records unfinished reload work before XML replacement. Failed reloads report an error and retry without rewriting identical XML; successful unchanged configurations do not reload. Python tests cover error propagation; native Windows tests cover pipe failure and retry. |
| Medium | Mode matching ignored refresh rate. | Matching includes refresh and standalone validation rejects out-of-range values, including explicit zero. Native Windows fixtures cover equal dimensions at different rates and duplicate idempotence. |
| Medium | Discovery merged distinct computers by friendly/short name and could assign the wrong pairing identity. | Merge uses overlapping normalized full addresses; pairing requires a unique address match after merging. Tests cover duplicate labels, distinct domains, ambiguous pairings, and addresses learned from another discovery source. |
| Medium | Initial backend/config errors were hidden behind “Add your first computer.” | A shared diagnostic banner remains visible without a selected computer; failed catalog reads suppress misleading onboarding. Real-QML tests use failing fake CLIs. |
| Medium | Retry status could say “attempt 4 of 3.” | Status reports retry 1–3 directly. QML tests cover each retry and expiry. |
| Medium | Discovery failures looked like empty successful results; failed setup reads left spinners running. | Failures/warnings, completion, and empty results are distinct. Retry controls retain the requested computer identity. QML tests cover catalog/get/discovery failure and recovery. |
| Medium | Host/SSH/adapter edits retained stale inspection results and helper-install choices. | Subject changes invalidate inspection and derived display selections; setup controls prevent edits during requests. Helper installation requires fresh inspection. QML tests preserve unrelated edits while invalidating changed subjects. |
| Low | Dead symbols and test-only production UI obscured the implementation. | Removed the unused host storage import, Windows ROOT constant, and hidden setup-test button. Tests invoke the actual check function. Compatibility/recovery/public CLI paths were retained. |
| Low | Dropdown chevrons were missing and the clickable service chip lacked keyboard activation. | Corrected the icon property and added keyboard/accessible activation and a focus outline. Qt tests pass; the compact matching preview was visually inspected. |
| Low | Documentation mixed implemented/planned features, contradicted Windows defaults, and labeled historical counts current. | README, extraction, UI, backend, launcher, architecture, and validation docs now distinguish implemented behavior, persistent configuration changes, historical measurements, and outstanding work. |

Implementation and tests can be inspected in [session management](../src/server.rs),
[supervision](../src/supervisor.rs), [window-rule editing](../src/windowrule.rs),
[discovery](../remote_desktops/setup.py),
[mode synchronization](../remote_desktops/windows/VirtualDisplayModes.ps1),
[manager UI](../ui/qml/Main.qml), and [guided setup](../ui/qml/SetupDialog.qml).

## Independent review disposition

The final reviewer verified the main findings from source and accepted their
narrow fixes. The post-implementation review found no blocking regression in
the reviewed ownership/concurrency changes. It requested three small follow-ups,
all addressed: reject explicit zero refresh; flush reload intent before replacing
XML; and document Sunshine's compositor-free fallback consistently, including
its valid `auto` configuration.

The review did not recommend speculative adapter deletion, merging the Qt and
daemon processes, automatic host migration, installation, or main-branch
promotion. No required check was removed, renamed, or weakened. The existing
Windows policy test entry point now includes isolated mode-sync tests.

## Remaining limitations and deliberate deferrals

- **Sunshine log duration bound:** verified matching rereads from the launch
  cursor. More than 131,072 bytes or 65,536 characters causes fail-closed loss of
  verification, even in a healthy long/noisy session. The helper boundary now
  enforces the same limits, and a regression proves prior verification is revoked.
  An incremental parser is deferred: it must preserve typed launch identity,
  partial lines/JSON, capture state, rotation detection, and mismatch revocation
  without persisting raw logs. Advancing the offset alone is unsafe.
- **Abrupt supervisor death:** the child guard handles ordinary error unwinding,
  not SIGKILL between spawn and durable PID publication. A child handshake or
  equivalent durable identity design is separate work.
- **Storage stalls:** launch-lock contention no longer blocks unrelated requests,
  but synchronous file writes/fsync still occur under the map mutex. No claim is
  made that arbitrary stalled storage is isolated or that streaming latency improved.
- **External editors:** advisory locking and content comparisons protect
  cooperative window-rule edits and detected external changes. They cannot make
  an uncooperative editor racing the final rename transactional.
- **Shutdown UX:** confirmation for closing the entire manager with an unsaved
  setup draft remains an enhancement. Existing Escape/Cancel draft confirmation
  remains; closing the manager does not disconnect streams.
- **Platform validation:** no real Sunshine/Moonlight stream, host display,
  pairing, live configuration, or installed desktop was changed for this audit.
  Native Windows execution and real Windows/macOS streaming/recovery remain
  separate validation requirements.

## Final local validation

- Repository validator and whitespace checks passed.
- Rust format, Clippy with warnings denied, 13 unit tests, and build passed.
- All 58 Python tests passed.
- All 41 daemon/CLI/supervisor integration tests passed with isolated fake hosts
  and clients.
- Qt build and all 27 CTest checks passed, including real-QML regression tests
  and the preview matrix. Compact matching rendering was inspected.
- Native Windows PowerShell tests were added to the existing policy suite but
  were not run on this Linux machine. GitHub's required checks must pass on the
  final PR revision before merging. Local results do not establish merge readiness
  or real streaming performance.
