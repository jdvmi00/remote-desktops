# Development, CI, and releases

## Current state

`develop` contains the standalone Rust backend and host adapters. `main` still
contains the locked bootstrap. There is no published application release,
installable package or Omarchy marketplace submission yet. A development Qt
manager is available for configured computers.

The initial CI/workflow bootstrap is complete. Its history was subsequently
linearized at the owner's request. This is not an application release and
creates no release tag. Future promotion requires an explicit release
instruction; repairing existing history is governed separately below.

## Development

1. Inspect git status and preserve existing work. Start a feature branch from
   current `develop`; do not develop directly on `main`.
2. Implement changes and run the commands in `.github/workflows/test.yml`.
   Run the repository validator; `cargo fmt --check`;
   `cargo clippy --all-targets --locked -- -D warnings`; `cargo test --locked`;
   `cargo build --locked`; `python3 -m unittest discover -s tests -v`; and
   `python3 tests/integration.py -v`.
3. Push the feature branch and open a PR targeting `develop`.
4. Wait for `test`, `windows-check`, and `windows-display-policy` on the current PR revision. Resolve
   conversations and rebase onto the base branch when GitHub requires it.
5. Rebase merge through the PR using its checked head SHA, without admin bypass.
   Do not use merge commits or squash merging. Keep working from `develop`.

Both integration branches require up-to-date checks, PRs, resolved
conversations, administrator enforcement, and linear history. Force pushes are
enabled for history rewriting; branch deletion remains prohibited. This is a
solo-maintainer workflow: zero additional approvals are
required. `main` has an additional lock between releases and remains the default.
Tags matching `v*` cannot be updated or deleted, including by administrators.

## History rewriting

History may be rewritten for rebasing and cleanup; do not rewrite unrelated
work or published version tags. An explicit owner instruction is required to
unlock or rewrite `main` outside a release.

1. Fetch current refs, inspect local status and the affected history, and record
   the expected full remote SHA. Do not create backup bundles unless requested.
2. Prepare linear replacement commits and verify the intended tree changes.
   Run local checks and obtain passing GitHub checks for the replacement SHA
   before updating an integration branch.
3. Use `--force-with-lease=refs/heads/BRANCH:EXPECTED_SHA`, never plain force.
   If the lease fails, stop and reconcile new remote work; do not replace the
   expected SHA blindly.
4. Required checks and linear history remain enforced. If GitHub's PR rule
   blocks an explicitly authorized ref repair, temporarily lift only that PR
   requirement on the affected branch for the repair, then restore it in a
   `finally` block. Do not use this exception for ordinary feature delivery.
   Unlock `main` only for the authorized operation and relock it immediately.
5. Read back the branch SHA and protections, verify push CI on the resulting
   revision, and update the local checkout without discarding uncommitted work.

## What CI proves today

`test` runs the repository checks, Rust format/clippy/unit tests, Python host
recovery tests, and real daemon/CLI/supervisor integration with fake hosts and
clients on Ubuntu. `windows-check` validates repository content and Python
Windows transport/recovery behavior on a native Windows runner.
`windows-display-policy` runs the extracted PowerShell policy, C# ABI checks,
and atomic journal tests on Windows. All three jobs are required.

These checks establish tested lifecycle and recovery contracts, not real
Moonlight connectivity, video performance, or host hardware behavior. Real
macOS/Windows streaming and display recovery require separate validation.

CI has read-only repository permissions and does not install the application,
touch real hosts, or publish anything. Release delivery is an explicit manual
workflow, as in Hypertile. Build/upload automation should be added alongside
real packaging; there are currently no installable artifacts to publish.

## Authorized releases

1. Obtain an explicit release instruction. Prepare the version, changelog,
   package contents, dependency declarations, installation/migration/removal
   instructions, and recovery validation on a feature branch from `develop`.
2. Pass relevant local suites and GitHub checks. Rebase merge into `develop`, then open
   a release PR from `develop` into `main`. Do not include unfinished features.
3. Wait for all required checks on the release PR's current revision. Leave
   `main` locked during preparation and review.
4. For the authorized promotion only, unlock `main` while retaining required
   PRs, checks, and administrator enforcement. Rebase merge the release PR once and
   immediately lock `main` again. If promotion fails, restore the lock before
   other work. Read back the protection settings and record the resulting full SHA.
5. Verify the push checks on that exact `main` SHA. Create a new version tag
   pointing to it and publish the reviewed artifacts and release notes. Never
   move an existing release tag.
6. Verify published artifacts and any explicitly authorized package updates.
   Keep `main` locked and continue development on `develop`.

Installation on the developer's desktop is separate from CI and publication.
Official Omarchy inclusion, package repository acceptance, and any optional
plugin marketplace approval are separate processes; do not claim approval from
a successful CI run. This repository has no authority over Hypertile's frozen
release candidate or marketplace submission.
