# Desktop launchers and window identity

## Install from a source build

Configure and pair the computer using [backend setup](BACKEND.md), then:

```sh
cargo build --release --locked
./target/release/remote-desktops launcher list
./target/release/remote-desktops launcher install macbook
```

The application menu now contains **MacBook (Remote Desktop)**, using the
configured Moonlight title without its ` - Moonlight` suffix. Repeat `install`
for each configured computer. It creates
`$XDG_DATA_HOME/applications/remote-desktops-COMPUTER.desktop`, defaulting to
`~/.local/share/applications`. It never copies pairing certificates or creates
workspace rules. Entries use the standard `computer` icon.

The entry runs `remote-desktops open COMPUTER` with the absolute path of the
binary that installed it. Keep this source checkout and release binary in place;
rerun `launcher install` after moving the checkout. This is a development
installation, not a portable package or a published Omarchy release.

`open` selects the configured default profile, starts the daemon if needed,
waits up to sixty seconds for a matched window, and focuses it. Reopening an
active computer reuses its client. A pending connection continues in the daemon
if the launcher times out. Errors appear as desktop notifications when
`notify-send` is available; CLI errors also go to stderr. `connect` remains the
immediate, asynchronous command for scripts; `open` is intended for launchers.

An active legacy Hypertile stream controller still requires explicit handoff.
Installing an entry does not stop another controller or migrate host state.

Update an entry by running the same install command. Remove it with:

```sh
./target/release/remote-desktops launcher remove macbook
```

Removal affects only that generated desktop entry, not configuration, a running
connection, or its recovery journal. Installer/remover refuse symlinks and files
without their ownership markers. Exec arguments follow desktop-entry escaping,
without invoking a shell. See the [desktop entry Exec specification](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html).

## Matching contract for Scenes

Moonlight Qt 6.1 hardcodes a common Wayland app ID and overwrites SDL WM-class
environment variables. A distinct desktop filename does not change the stream
window's class. See [Moonlight 6.1 source](https://github.com/moonlight-stream/moonlight-qt/blob/v6.1.0/app/main.cpp).
No Moonlight fork or library injection is required here.

`launcher list` and session `status` expose this metadata:

```json
{
  "desktop_id": "remote-desktops-macbook.desktop",
  "match": {
    "class": "com.moonlight_stream.Moonlight",
    "title": "MacBook - Moonlight",
    "tag": "remote-desktops-macbook"
  }
}
```

- Use the desktop ID to launch, and exact class **plus title** to match a window
  across launches. Configuration rejects duplicate final titles, because they
  cannot identify different computers reliably. Configure distinct host names
  in Moonlight/Sunshine if two hosts currently produce the same title.
- The backend assigns the static Hyprland tag only after matching its owned
  process and final title. Generic compositor integration may also use that
  tag. Temporary renderer/startup windows are not considered ready targets.
- Live actions additionally verify process ownership, window address, PID,
  numeric stable ID, class, and title. Neither a tag nor a title alone authorizes
  closing/signaling a process.
- Entries intentionally omit `StartupWMClass`; it cannot promise separate
  Wayland taskbar grouping for clients that share Moonlight's app ID.

The metadata is implemented; consuming it in generic Hypertile Scenes remains
a separate feature. Class-only matching is insufficient for simultaneous hosts.

## Initial window state

Omarchy's default Moonlight rule requests fullscreen. On first matching a new
stream window, Remote Desktops assigns its tag and clears internal/client
fullscreen once. The compositor continues to choose placement and size. A brief
startup fullscreen transition is possible before the matching event arrives.

`remote-desktops window-rule install` (Preferences in the manager) appends a
marked block to `~/.config/hypr/hyprland.lua` with a rule that opens Moonlight
windows tiled. User files load after Omarchy's defaults and the last matching
anonymous rule wins, so the window opens tiled from the start and the startup
transition disappears. The block is replaced or removed as a unit, a one-time
backup of the file is kept beside it, and Hyprland's config check runs after
every change. Malformed block markers are rejected before writing. Failed
reload or validation restores the previous file if it still matches the app's
write; concurrent external edits are preserved and reported for manual review.
App edits use the adjacent `hyprland.lua.remote-desktops.lock`; manual editors
should honor it too. Content comparisons cannot make an uncooperative write
racing the final replacement transactional. A hand-written rule is detected
and left alone. The rule applies to every Moonlight window, not only managed ones.

There is no ongoing fullscreen or placement correction. User fullscreen choices
survive repeated opens, workspace changes, and daemon restart. Reconnect creates
a new stream window with fresh windowed startup. A profile whose resolution is `auto` opens at the last known size and does not
restart on its own; Refit restarts it once to match the current window. Existing windows adopted from
the older backend are preserved; reconnect once to get their new startup tag.

The startup action is consumed durably before dispatch to avoid replay after a
crash. If initialization fails, status records an error and the user can leave
fullscreen manually. No global Omarchy rule is edited, so independently launched
Moonlight sessions keep their normal desktop policy.
