# Repository workflow

- Inspect git status before editing and preserve unrelated work.
- Keep this application independent of Hypertile. It owns connections and host
  recovery, not layouts or workspace placement.
- Read `docs/EXTRACTION.md` before importing or restructuring stream code.
- Preserve the original license notices and record source revisions when
  extracting code from another repository.
- Do not migrate live configuration, transfer controller ownership, install
  runtime code, or change host display settings merely to test repository changes.
- Never commit credentials, pairing material, real computer profiles, logs,
  recovery journals, or runtime state. Use synthetic fixtures.
- Run tests relevant to changed behavior. Distinguish mocked checks from actual
  macOS/Windows streaming and recovery validation.
- Work in this repository does not authorize changes to Hypertile's frozen
  `main` branch, marketplace submission, or published tags.
