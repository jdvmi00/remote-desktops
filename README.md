# Remote Desktops

A standalone remote desktop manager for Omarchy, built around Moonlight and Sunshine.

Open a computer from the application launcher and use its remote desktop as an
ordinary window. Move it between workspaces, resize it, or assign it to a
Hypertile Scene like any other application.

## Status

The standalone backend is implemented on `develop`: a Rust daemon and CLI with
Moonlight process supervision, journaled host recovery, and per-computer desktop
launcher entries. The Qt graphical manager now provides connection controls for
adding, editing, and connecting computers paired in Moonlight. Installable packaging is not implemented yet.
`main` remains the locked project bootstrap; there is no published app release.

The host adapters come from the remote-stream work in
[Hypertile](https://github.com/jdvmi00/hypertile). Moonlight remains the video
client and Sunshine remains the remote host. This project manages computer profiles, connection lifecycle, host display
recovery, and user controls.

## Implemented behavior

- Launch a saved computer/profile from a desktop entry or command.
- Reuse an existing connection when the same target is opened again.
- Keep remote windows independent of any layout or workspace assignment.
- Provide connection status, reconnect, disconnect, and display restoration.
- Preserve Moonlight pairing and existing host authentication.
- Offer a standalone computer/settings window with discovery and guided setup.
- Configure an Omarchy Linux host's [keep-awake policy](docs/HOST_POWER.md)
  for active Sunshine streams, with Off, AC-only, and Always options.

Installable packaging and an optional Omarchy bar plugin remain planned.

Hypertile Scenes uses generic application launch and window matching.
Hypertile owns placement; Remote Desktops owns connections.

See [the extraction plan](docs/EXTRACTION.md) for the implementation sequence,
migration requirements, and acceptance criteria.

## Development

Use a feature branch from `develop` and rebase merge its PR into `develop`. `main`
remains locked between authorized releases. See [AGENTS.md](AGENTS.md) and
[the development and release workflow](docs/RELEASING.md).

Build and run from the checkout on Linux (Python 3 and Rust are required):

```sh
cargo build --locked --release
./target/release/remote-desktops --help
./target/release/remote-desktops computers
./target/release/remote-desktops launcher install macbook
./target/release/remote-desktops open macbook
./target/release/remote-desktops connect macbook
./target/release/remote-desktops status --json
./target/release/remote-desktops disconnect macbook
./target/release/remote-desktops start
./target/release/remote-desktops settings remove macbook
```

Configure and pair your computers first; see [backend usage](docs/BACKEND.md).
See [desktop launchers and window matching](docs/LAUNCHERS.md) for application
menu entries, existing-window reuse, and the matching contract for future Scenes.
The first connection starts the daemon if needed. Commands acknowledge intent;
use `status` to observe connection or restoration progress.

### Rebuilding during development

Build both the Rust backend and Qt manager with:

```sh
python3 scripts/dev.py build
```

Before rebuilding, disconnect all streams and wait for any pending display
restoration to finish. Close the manager, then stop the development daemon.
Closing the manager or stopping the daemon alone does not disconnect streams.
After rebuilding, start these in separate terminals from the checkout:

```sh
python3 scripts/dev.py daemon
python3 scripts/dev.py ui
```

The manager checks that it is using this checkout's current backend build.
See [the development loop](docs/UI.md#local-development-loop) for details.

On the development workstation with the local `remote-desktops-dev` helper,
open **Remote Desktops (Development)** from the application launcher, or run
`remote-desktops-dev`. After disconnecting streams and completing recovery,
the rebuild sequence for its temporary user services is:

```sh
systemctl --user stop remote-desktops-development-ui remote-desktops-development-daemon
remote-desktops-dev build
remote-desktops-dev
```

The helper and desktop entry are local setup, not files installed by a checkout
or a published package. They run the repository build; the last command starts
the development daemon if needed and opens the manager.

Run the checks locally:

```sh
python3 scripts/check.py
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --locked
cargo build --locked
python3 -m unittest discover -s tests -v
python3 tests/integration.py -v
cmake -S ui -B build/ui -DCMAKE_BUILD_TYPE=Release
cmake --build build/ui --parallel 2
ctest --test-dir build/ui --output-on-failure
```

GitHub Actions tests the Rust/Linux backend, Python host recovery, and the
Windows PowerShell display policy on its native runner. Integration tests use
isolated fake clients and hosts; they do not establish real streaming performance.
See [architecture](docs/ARCHITECTURE.md) and [source provenance](docs/PROVENANCE.md).
Initial local measurements and their limits are in [validation](docs/VALIDATION.md).
The [2026-09-07 audit](docs/AUDIT.md) records verified fixes, test results, and
remaining limitations.

## License

MIT. This project is independently maintained and is not an official Omarchy,
Moonlight, or Sunshine application.

## Graphical manager

A separate Qt 6/QML manager is available on `develop`. It finds computers on
Tailscale and the local network, pairs them through Moonlight with a PIN,
configures managed macOS and Windows display recovery over SSH, and provides
connection controls, profile selection, and per-computer launchers, following
the active Omarchy theme and desktop font. Closing it leaves connections
running.

See [UI build, preview, and interaction guide](docs/UI.md). Pairing and computer
configuration still use Moonlight and the backend setup guide; no installable
release has been published.
