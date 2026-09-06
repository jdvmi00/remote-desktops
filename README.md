# Remote Desktops

A standalone remote desktop manager for Omarchy, built around Moonlight and Sunshine.

Open a computer from the application launcher and use its remote desktop as an
ordinary window. Move it between workspaces, resize it, or assign it to a
Hypertile Scene like any other application.

## Status

Project initialized; the application has not been extracted or packaged yet.
There is no standalone installation or runnable release at this stage.

The initial implementation will come from the remote-stream work in
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

## License

MIT. This project is independently maintained and is not an official Omarchy,
Moonlight, or Sunshine application.
