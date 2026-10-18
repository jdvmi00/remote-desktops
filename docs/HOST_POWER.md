# Host power while streaming

Select a saved Linux computer in the manager, then **Host power…**. Enter an
SSH alias from this computer's SSH configuration and choose **Check host**.
The account must own the remote Omarchy desktop and Sunshine user service.
SSH uses existing keys and strict host-key checking; the application stores no
password. Applying a policy remembers only the SSH alias in the local computer
configuration.

Choose a policy, disconnect every Sunshine client, then **Apply on host**:

- **Off** stops and disables the host helper and removes its lid-binding block.
- **On AC power** keeps the host awake during streams while external power is
  available. Unplugging releases inhibition. Unknown power state is treated as
  battery power.
- **Always** also permits inhibition on battery.

AC power is the suggested choice when first opening the dialog. No policy is
enabled until Apply is selected. This is a host-wide setting for every Sunshine
client, independent of the local connection profile, manager, or daemon. Apply
changes the host immediately; closing the dialog does not undo it.

After connecting, use **Check host** to confirm that inhibition is active before
closing the lid. Stream detection is polled, so protection is not instantaneous
at connection startup.

The helper holds temporary systemd sleep, idle, and lid-switch inhibitors. Its
Omarchy lid handler skips lid-close locking only while a live inhibitor lease
exists. Otherwise the normal Omarchy handler runs. Manual locking and Omarchy's
idle-lock timer remain available; this feature does not change their settings.
Sleep inhibitors also affect ordinary explicit suspend requests while held.

Keeping the computer awake does not provide a virtual display or guarantee
capture with the panel powered off. Validate lid-closed video on the actual
host. Display creation, mode switching, and display recovery remain separate.

## Supported hosts

The first implementation supports Omarchy Linux, a systemd user session, Python
3.11 or later, and Sunshine **2026.914.233613**, with the packaged
`app-dev.lizardbyte.app.Sunshine.service` and `/usr/bin/sunshine`. A working
Hyprland session must be available to the SSH account. The helper needs
one unambiguous desktop session when SSH does not inherit a compositor instance.
The helper discovers that instance before changing files. It also needs
permission to take systemd inhibitors. Custom user-defined lid-close bindings
are preserved: enabling refuses them rather than replacing their behavior.

Sunshine's public `currentgame`/busy flag describes the application, which may
remain running after all clients disconnect. Its paired-client API also does
not report connected sessions. This adapter instead counts Sunshine's
`session::video` worker threads under the verified service PID. Encoder threads
can inherit that name, so the reported value is a worker count, not a client
count. Detection includes the short connection startup and teardown periods in
which Sunshine owns those workers. Multiple clients keep the inhibitor held
until the last worker ends. Network timeouts use Sunshine's own session teardown.
The local HTTP server must also respond with the expected host identity; a
frozen process loses inhibition even if its task entries still exist.

This contract was checked against Sunshine source revision
[`63d35f702ee9e362e43263742981836ec0710384`](https://github.com/LizardByte/Sunshine/blob/63d35f702ee9e362e43263742981836ec0710384/src/stream.cpp).
Other versions require reviewing and validating the observation contract before
adding them to the supported set. Installation records the binary's digest; a
package update releases inhibition until the policy is reapplied. Unknown
versions can still disable an existing policy.

## Files and lifetime

The host installs private files under `~/.local/share/remote-desktops/host-power`
and a user unit named `remote-desktops-host-power.service`. The unit starts with
the graphical session. A marked block in `~/.config/hypr/hyprland.lua` installs
the conditional lid handler; the original file is backed up once as
`hyprland.lua.before-host-power`. Applying validates the compositor configuration
and rolls back its file changes on failure.

The helper checks the service PID, executable, pairing UUID, worker count, and
power state every two seconds. It caches the executable digest until the file's
identity or metadata changes. It reads the host UUID from Sunshine's local state
file but never copies or transmits its pairing material. It does not read screen
content, input, Sunshine web credentials, or raw Sunshine logs.

Inhibition belongs to a child process with an inherited systemd inhibitor file
descriptor. A heartbeat pipe ties it to the host helper. Parent exit closes the
pipe; a stalled parent loses the lease after six seconds. The helper releases
the inhibitor if the host state becomes unreadable, Sunshine exits or changes,
AC power is lost under the AC policy, or the last stream worker ends. Runtime
leases are private and do not survive a reboot.

**Check host** reports the policy, worker count, power source, helper status,
and current inhibition. It is read-only. Apply refuses active streams and
serializes host configuration writes. It does not stop Sunshine or install a
replacement streaming engine. A stream starting concurrently with setup is
not prevented by the SSH check; perform setup with clients disconnected.

## Validation

Isolated Python tests cover worker identity, multiple clients, AC transitions,
stale leases, parent exit and heartbeat loss, observer failure, setup rollback,
unsupported builds, custom lid bindings, and SSH error handling. CLI integration
tests use fake SSH and preserve saved identities and unrelated configuration.
Qt tests exercise the explicit check/apply flow without contacting a host.
These tests do not establish real lid-closed capture or suspend behavior.
