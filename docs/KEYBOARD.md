# Local and remote keyboard commands

In **Edit → Keyboard shortcuts**, choose where system shortcuts go for the
selected connection profile:

- **Remote desktop while focused:** send Super, Alt+Tab, and similar shortcuts
  to the remote desktop whenever its Moonlight window is focused.
- **Remote desktop only in fullscreen:** capture system shortcuts in fullscreen.
- **Keep system shortcuts on this computer:** retain local compositor shortcuts.

New GUI-created profiles use capture while focused. Existing profiles keep their
saved policy; a missing `system_keys` still means `never`. Editing an old draft
that omits this field preserves the saved value. Capture changes require
**Disconnect**, then **Connect**. **Reconnect** uses the existing session snapshot.
The connection view reports the running session's policy, not an unsaved draft.

## Run one local command

Open **Preferences → Keyboard & local commands**, or **Configure prefix…** from
computer settings. Enable the prefix and save. F12 is the initial suggestion;
choose a different shortcut if it is already bound locally. The same prefix
applies to every managed Moonlight window on this local computer.

1. Focus the remote desktop, press the prefix, and release it.
2. An on-screen **LOCAL COMMAND** hint appears.
3. Use your existing local shortcut: for example Super+Shift+Right to move the
   outer tile, or Super+Space to open the local menu.
4. Releasing that combination returns system shortcuts to the remote desktop.

The prefix again or Escape cancels. An unused prefix cancels after the configured
2–15 seconds (5 by default). Leaving or closing the window also cancels. Local
shortcuts that enter a Hyprland submap retain that submap; the prefix does not
reset user-defined modes. It is inactive while a user submap is selected.
Unbound keys still reach the focused application; this is an escape for existing
local shortcuts, not a separate command interpreter. Repeating a held local
shortcut retains its usual repeat behavior until release or timeout.

The local prefix is reserved inside managed remote windows. To use that key on
the remote host, choose a different prefix. Ctrl+Alt+Shift+Z remains Moonlight's
independent capture toggle. For fullscreen-only capture, the prefix is useful
in fullscreen; when capture is off, normal local shortcuts already work.

## Ownership and removal

The Rust `keyboard status|save` CLI owns a marked block in
`~/.config/hypr/hyprland.lua`. `save` accepts bounded JSON on stdin:
`enabled`, `prefix`, `timeout`, and the `revision` returned by `status`.
It backs up the original file once, serializes edits with the same lock as
`window-rule`, checks the revision and existing compositor bindings, atomically
writes, reloads, and checks configuration errors. Rejected configuration is
rolled back without overwriting concurrent manual edits. Existing bindings are
never unbound. An existing unmodified Escape binding conflicts with cancellation
and is reported before writing. Physical-code bindings that cannot be resolved
unambiguously are treated conservatively as conflicts.

Disabling keeps the chosen prefix and timeout but removes all feature handlers
and rules from the managed block. Prefix edits apply immediately to existing
managed windows; they do not reconnect clients or change host settings.

The embedded Lua integration requires Hyprland's Lua APIs: `hl.bind` handles,
window tags/rules, keyboard and focus events, timers, and notifications. It was
checked against Hyprland 0.56.2. Other desktops can use the capture policies
without this integration. If the compositor rejects an API, saving rolls back.

Moonlight retains input transport. The integration temporarily tags only the
focused managed Moonlight window with `no_shortcuts_inhibit`, so the compositor
uses its existing bindings, including Lua callbacks from custom layouts. It
never owns layouts or imports Hypertile. It does not synthesize keys, relay
keyboard input through Rust/Qt/Python, or record keys. Transient state lives in
the compositor; closing the manager or restarting the daemon cannot strand it.
Reloading the integration clears its old transient tags. Timer callbacks cancel
the hint and tag; a deferred release cleanup lets release-triggered bindings run.

## Validation

`lua tests/local_command.lua` exercises cancellation, repeated timers, modifier
handling, focus changes, unmanaged windows, tag changes, close, submaps, and cleanup
with a synthetic compositor. CI runs it with Lua 5.4. Rust/CLI tests cover parsing,
conflicts, stale revisions, disable, rollback, and capture-policy round trips.
Qt tests cover draft/save/discard and rendering; all actions use fake backends.

A local isolated Hyprland 0.56.2 session with a synthetic SDL keyboard-grab client
also verified ordinary shortcuts reaching the client, prefixed shortcuts invoking
an existing compositor Lua callback, repeated prefix use, Escape cancellation,
and managed-tag changes without reloading.
This establishes compositor routing with SDL capture, not actual Sunshine input
or video streaming. Real Omarchy-to-Omarchy use still needs keyboard validation
on the two computers, including their keyboard layouts and custom bindings.
