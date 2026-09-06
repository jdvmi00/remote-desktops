# Extraction from Hypertile

The first backend extraction is implemented on `develop`; see
[architecture](ARCHITECTURE.md), [usage](BACKEND.md), and
[provenance](PROVENANCE.md). Per-computer [launcher entries](LAUNCHERS.md) and
window matching are implemented. Live MacBook handoff has been tested explicitly;
there is no automatic migration. Graphical UI, generic Scenes support, and
packaging remain subsequent features.

## Boundary

Remote Desktops owns computer/profile configuration, managed Moonlight
processes, connection and reconnect state, host display preparation and
restoration, audio policy, input controls, diagnostics, and quality reporting.

Hypertile owns layouts, reservations, workspace placement, navigation, and
Scenes. Remote Desktops must work without Hypertile installed or running.
An optional Omarchy shell plugin is a client of the app, not its process owner.

Moonlight owns pairing, media transport, decoding, and the remote desktop
window. Sunshine owns capture, encoding, and remote input. This extraction does
not replace either project or imply changes to their upstream code.

## Initial source map

The source is `jdvmi00/hypertile`, developed from `develop`. Record the exact
source revision and any additional patches when importing code; do not use or
modify its frozen marketplace branch as part of extraction.

| Existing area | Treatment |
| --- | --- |
| `stream/controller.py` | Extract lifecycle and configuration; remove scene, zone, and layout dependencies |
| `stream/mac_display.py` | Preserve host identity checks and display recovery behavior |
| `stream/windows_display.py`, `stream/windows/` | Preserve display policy, recovery journals, and host helpers |
| `stream/audio.py`, `stream/quality.py` | Extract relevant controls and measurements; remove tile assumptions |
| `bin/hypertile-stream` | Replace with an independent app command and startup path |
| `session/service.py` | Extract only needed shared IO utilities and window observation; do not import session/layout restoration wholesale |
| `session/streams.py` | Replace Hypertile-specific recovery integration with a documented app boundary |
| `stream/scenes.py`, `stream/browse.py`, Lua layout adapters | Keep in Hypertile; migrate callers to generic app integration |
| Stream and display tests | Port with their implementation; keep failure and recovery cases |

## Implementation sequence

1. Extract a headless backend and command line interface with isolated config,
   state, runtime paths, and tests. Preserve recovery before adding UI.
2. Provide per-computer launch targets and desktop entries. Establish reliable
   window matching for simultaneous Moonlight sessions, including startup
   windows and reconnects. Verify the matching mechanism against Moonlight;
   do not assume it supports a configurable Wayland app ID.
3. Add a standalone computer list, configuration, status, and recovery controls.
   Choose the UI toolkit when the backend interface is defined.
4. Add generic launch-if-missing and existing-window reuse to Hypertile Scenes.
   Applying a Scene may place a window; ongoing app reconciliation must not
   override a user's later workspace move.
5. Package for Arch/Omarchy with desktop entries, icons, dependency metadata,
   upgrade/uninstall behavior, and any required user service. Add an optional
   shell plugin after the standalone app works.

## Migration and recovery

- Never allow both controllers to manage the same session or recovery journal.
- Define an explicit handoff for existing connections and outstanding display
  restoration before enabling the standalone controller.
- Preserve host identity, compare-before-restore checks, recovery data, and
  manual host changes across crashes, disconnects, and upgrades.
- Reuse Moonlight's existing pairing. Do not copy certificates, passwords,
  local machine configuration, or live state into this repository.
- Keep configuration migration explicit and reversible; retain the original
  until the new app has verified its imported configuration.
- Test closing a remote window and closing the manager UI separately. Closing
  the manager must not accidentally terminate active sessions.

## Acceptance criteria for the first runnable version

- Connect to a configured host without Hypertile or its Lua modules.
- Opening the same launch target twice does not create duplicate sessions.
- Move and resize a connected window freely without reconnecting or snapping back.
- Run two different computers concurrently and match their windows correctly.
- Disconnect and recover managed display settings, including after controller
  failure, host unavailability, and independently changed host settings.
- Preserve the existing macOS and Windows recovery regression coverage.
- Report local and real-host validation separately; require a Windows runner
  for PowerShell policy checks and real hosts for end-to-end streaming claims.

Official inclusion in Omarchy is a separate upstream proposal after the app is
usable independently. It is not a prerequisite for development or installation.
