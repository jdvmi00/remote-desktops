# Repository workflow

Read [docs/RELEASING.md](docs/RELEASING.md) before changing branches, CI,
release metadata, tags, or GitHub settings.

## Branches and preservation

- `main` is the default branch and is locked between explicitly authorized
  releases. It currently contains project scaffolding, not an installable app.
- Work on feature branches based on `develop`; target implementation PRs at
  `develop`. Ordinary development requests do not authorize promotion to `main`.
- Inspect git status before editing and preserve unrelated work. Stage only
  your changes; never discard or commit unrelated user changes.
- Use rebase merging for all PRs. Do not create merge commits or squash commits;
  rebase feature branches onto the current target branch when updating them.
- History rewriting is allowed for rebase and history cleanup. Fetch first,
  inspect the affected commits, and push with
  `--force-with-lease` bound to the expected remote SHA, never plain `--force`.
  Preserve unrelated work and rerun required checks on rewritten revisions.
- Never delete `main` or `develop`, move published release tags, change the
  default branch, or bypass CI as a routine fix.
- Unlocking or moving `main` requires an explicit release or history-repair
  instruction from the owner. Relock it immediately after the authorized work.

## CI and delivery

- `.github/workflows/test.yml` defines the checks. Keep CI running on pushes to
  `develop` and `main`, and on every PR without path filters.
- Run the repository check, Rust format/clippy/tests/build, Python host tests,
  and `python3 tests/integration.py -v` locally, as listed in the workflow.
  Tests must use isolated fake clients/hosts; real streaming validation is separate.
- Before merging, all GitHub checks `test`, `windows-check`, and `windows-display-policy` must pass on the
  current PR revision, with the branch up to date and conversations resolved.
  No additional reviewer is required for this solo-maintainer repository.
- Rebase merge with the checked head SHA. For an authorized integration-branch
  rewrite, follow the lease and protection-restoration steps in RELEASING.md.
- Fix failures without weakening, skipping, or renaming required checks to
  evade protection. Read-only job permissions are the default.
- `test` exercises the Rust/Linux backend and Python recovery algorithms;
  `windows-check` checks portable repository/transport behavior;
  `windows-display-policy` runs the real PowerShell policy/journal suite.
  None of these jobs proves actual video streaming on a real host.
- Distinguish mocked checks from actual macOS/Windows streaming and recovery
  validation. Use a Windows runner for Windows checks; never claim an unavailable
  local platform test passed.
- Development CI must not publish releases, push to `main`, update package
  registries or marketplace submissions, or install code on a user's desktop.
- Follow `docs/RELEASING.md` for an authorized release. A green CI run is not
  release authorization or upstream Omarchy approval.

## Code stack

- Keep the daemon, CLI, and client supervisor in Rust. Preserve the narrow Python
  host-operation boundary and its durable recovery tests when changing adapters.
- The planned UI is a separate Qt 6/QML process. Keep video/audio/input in
  Moonlight/Sunshine and keep Qt dependencies out of the daemon.
- Read `docs/ARCHITECTURE.md` before changing concurrency, IPC, supervision, or
  recovery ownership. Measure performance rather than claiming latency gains
  from the programming language or mock-client timing.

## Application boundaries and migration

- Keep this application independent of Hypertile. It owns connections and host
  recovery, not layouts or workspace placement.
- Read `docs/EXTRACTION.md` before importing or restructuring stream code.
- Preserve the original license notices and record source revisions when
  extracting code from another repository.
- Do not migrate live configuration, transfer controller ownership, install
  runtime code, or change host display settings merely to test repository changes.
- Never commit credentials, pairing material, real computer profiles, logs,
  recovery journals, or runtime state. Use synthetic fixtures.
- Work in this repository does not authorize changes to Hypertile's frozen
  `main` branch, marketplace submission, or published tags.
