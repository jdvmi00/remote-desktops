# Remote Desktops

A standalone remote desktop manager for Omarchy, built around Moonlight and Sunshine.

Open a computer from the application launcher and use its remote desktop as an
ordinary window. Move it between workspaces, resize it, or assign it to a
Hypertile Scene like any other application.

## Status

The standalone backend is implemented on `develop`: a Rust daemon and CLI with
Moonlight process supervision and journaled host recovery. The graphical manager,
desktop launcher entries, and installable packaging are not implemented yet.
`main` remains the locked project bootstrap; there is no published app release.

The host adapters come from the remote-stream work in
[Hypertile](https://github.com/jdvmi00/hypertile). Moonlight remains the video
client and Sunshine remains the remote host. This project will manage computer
profiles, connection lifecycle, host display recovery, and user controls.

## Planned behavior

- Launch a saved computer/profile from a desktop entry or command.
- Reuse an existing connection when the same target is opened again.
- Keep remote windows independent of any layout or workspace assignment.
- Provide connection status, reconnect, disconnect, and display restoration.
- Preserve Moonlight pairing and existing host authentication.
- Offer a standalone computer/settings window and, optionally, an Omarchy bar plugin.

Hypertile integration will use generic application launch and window matching.
Hypertile will own placement; Remote Desktops will own connections.

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
./target/release/remote-desktops connect macbook
./target/release/remote-desktops status --json
./target/release/remote-desktops disconnect macbook
```

Configure and pair your computers first; see [backend usage](docs/BACKEND.md).
The first connection starts the daemon if needed. Commands acknowledge intent;
use `status` to observe connection or restoration progress.

Run the checks locally:

```sh
python3 scripts/check.py
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --locked
cargo build --locked
python3 -m unittest discover -s tests -v
python3 tests/integration.py -v
```

GitHub Actions tests the Rust/Linux backend, Python host recovery, and the
Windows PowerShell display policy on its native runner. Integration tests use
isolated fake clients and hosts; they do not establish real streaming performance.
See [architecture](docs/ARCHITECTURE.md) and [source provenance](docs/PROVENANCE.md).
Initial local measurements and their limits are in [validation](docs/VALIDATION.md).

## License

MIT. This project is independently maintained and is not an official Omarchy,
Moonlight, or Sunshine application.
