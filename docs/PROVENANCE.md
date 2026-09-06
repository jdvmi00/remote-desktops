# Source provenance

Host recovery and its regression cases were extracted from Jim Martin's
MIT-licensed [Hypertile source](https://github.com/jdvmi00/hypertile/tree/e3e42463d35d16b21fde8748c535c8faa84bbc8b).
The original copyright and MIT license are retained in this repository's LICENSE.

Source revision: `e3e42463d35d16b21fde8748c535c8faa84bbc8b`.
Only committed source at that revision was used. Uncommitted Hypertile workspace
movement changes were not imported, and no source repository file was changed.

| Original file | SHA-256 of original contents |
| --- | --- |
| `stream/controller.py` | `2db7d9d83c642caec4ce7b69dce9101cf36a5d003847ca3eb811f6d57633d8e9` |
| `stream/mac_display.py` | `b1706533cbf35e92c07d7fe03fe9fba17b2fbb9d7dbb74d53dcc2395ccb0ab89` |
| `stream/windows_display.py` | `bb401db14db84f77b1ec8555ddf6c32e9106cb078f28e024fdb4862630f1a606` |
| `session/service.py` | `cba6e81c8cdf5761717b998ee1076975b006c6eb8e589faa921dbe9fd56aeaa3` |
| `test/stream.py` | `79be0dcecfed63417b5cd455664c337651096cfd1392e5d3c86ebb1d0908a593` |
| `test/windows_display.py` | `cbaca4623a9c7c8d79e0626ca5738d4e812d44e3d9589245dba69ede160ad5e9` |
| `stream/windows/Display.cs` | `6a33bc23437d70e77c83fe939ab1176f7c172774ff85c0f116a65d04a2a0bc1a` |
| `stream/windows/Guard.ps1` | `728fb999b15c9e640783225c48f9b8bda51622c89cf20a1197f32894e2215925` |
| `stream/windows/Install.ps1` | `aea3b8dcb98b6e1ac081924a350a145ce8a13e635af0d2b6ed0ef5e828126bd3` |
| `stream/windows/Policy.ps1` | `c824d9ddcbd0e54dc149f30791ae64f3cd09ff6fe90d5255007799252cdec761` |
| `stream/windows/Test.ps1` | `a94f557a6c120f6902dc8a540532b0e8cb3090be604a17fae4e018b306caef0e` |

## Adaptations

- `remote_desktops/host.py` extracts configuration, pairing/probe, preparation,
  restoration, and Moonlight argument generation from the original controller.
  Imports are package-relative; default-profile validation is added. It contains
  no window, zone, scene, or controller ownership code.
- `remote_desktops/worker.py` provides a bounded JSON operation interface and a
  recovery-file lock, with topology/health logic from the original controller.
- `remote_desktops/storage.py` extracts atomic durable JSON IO from the session
  service; the session manager itself is not imported.
- `remote_desktops/mac_display.py`, `windows_display.py`, and `windows/` retain
  the original host adapters and Windows helper protocol, including legacy host
  paths/class/task names. This avoids an implicit host migration.
- `tests/test_host.py` ports host-only recovery cases and fixtures. Window and
  lifecycle behavior is tested against the new Rust backend in integration.py;
  log evidence parsing has corresponding Rust tests.
- `tests/test_windows_display.py` ports transport/recovery cases; the PowerShell
  policy/journal tests run unchanged on the Windows runner.
- Rust replaces the local controller, process launch/supervision, event
  observation, and CLI. The partial Python-controller extraction was removed.

No Moonlight or Sunshine source is vendored or modified. They remain separately
installed applications with their own licenses and release processes.
