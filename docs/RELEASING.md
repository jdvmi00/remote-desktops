# Development, CI, and releases

## Current state

This repository contains project scaffolding. It has no standalone application,
package, release version, or Omarchy marketplace submission yet.

The initial CI/workflow setup is a one-time bootstrap: merge the setup PR into
`develop` after both checks pass, then merge a bootstrap PR from `develop` into
`main` after both checks pass. Lock `main` immediately afterwards. This is not
an application release and creates no release tag. Future promotion requires
an explicit release instruction from the owner.

## Development

1. Inspect git status and preserve existing work. Start a feature branch from
   current `develop`; do not develop directly on `main`.
2. Implement changes and run the commands in `.github/workflows/test.yml`.
   Currently these are `python3 scripts/check.py` and
   `python3 -m unittest discover -s tests -v`.
3. Push the feature branch and open a PR targeting `develop`.
4. Wait for `test` and `windows-check` on the current PR revision. Resolve
   conversations and update from the base branch when GitHub requires it.
5. Merge through the PR without admin bypass. Keep working from `develop`.

Both integration branches require up-to-date checks, PRs, resolved
conversations, and administrator enforcement. They prohibit force pushes and
deletion. This is a solo-maintainer workflow: zero additional approvals are
required. `main` has an additional lock between releases and remains the default.
Tags matching `v*` cannot be updated or deleted, including by administrators.

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
2. Pass relevant local suites and GitHub checks. Merge into `develop`, then open
   a release PR from `develop` into `main`. Do not include unfinished features.
3. Wait for all required checks on the release PR's current revision. Leave
   `main` locked during preparation and review.
4. For the authorized promotion only, unlock `main` while retaining required
   PRs, checks, and administrator enforcement. Merge the release PR once and
   immediately lock `main` again. If promotion fails, restore the lock before
   other work. Read back the protection settings and record the full merge SHA.
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
