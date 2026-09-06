# Development, CI, and releases

## Current state

This repository contains project scaffolding. It has no standalone application,
package, release version, or Omarchy marketplace submission yet.

The initial CI/workflow bootstrap is complete. Its history was subsequently
linearized at the owner's request. This is not an application release and
creates no release tag. Future promotion requires an explicit release
instruction; repairing existing history is governed separately below.

## Development

1. Inspect git status and preserve existing work. Start a feature branch from
   current `develop`; do not develop directly on `main`.
2. Implement changes and run the commands in `.github/workflows/test.yml`.
   Currently these are `python3 scripts/check.py` and
   `python3 -m unittest discover -s tests -v`.
3. Push the feature branch and open a PR targeting `develop`.
4. Wait for `test` and `windows-check` on the current PR revision. Resolve
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

`test` runs on Ubuntu and `windows-check` runs on a native Windows runner.
Both validate tracked repository files, local Markdown file links, Python
syntax, and the regression tests for the repository checker. Windows checkout
uses LF endings for text through `.gitattributes`.

These checks do not establish Moonlight connectivity, host display recovery,
macOS behavior, or Windows display policy. When extracting the backend, add its
actual runtime suites in the same PR. When importing Windows display helpers,
add and require `windows-display-policy` running the real PowerShell policy
suite on Windows; do not substitute a successful placeholder job.

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
