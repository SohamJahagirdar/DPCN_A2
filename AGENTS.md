# Development workflow

- Continue ordinary development on `manas/research-network-resilience`. This is
  the persistent development branch for subsequent analyses; do not create a
  replacement or per-analysis branch unless the user requests one.
- `main` is the official baseline/published version. Do not switch to it for
  implementation, commit to it, merge into it, or push it without explicit user
  instructions. Inspect status and branch history before changing Git state.
- Preserve uncommitted work. Never discard, overwrite, stash, reset, or rebase
  work merely to obtain a clean checkout. Stop if unexpected changes or remote
  divergence make the intended continuation unsafe.
- Development commits contain source, tests, and documentation. Do not commit
  generated `outputs/`, `dashboard/index.html`, raw data, caches, processed
  intermediates, API keys, or secrets. The designated integrator handles official
  output regeneration separately. Do not add AI co-author trailers.
- Obtain the user's authorization before pushing. Push only the intended
  development branch, normally and without force; verify its remote ancestry
  and upstream first. The audit task authorizes its own development-branch push.
- Validate with synthetic tests and committed data when raw snapshots are absent.
  Do not run a full build, call research APIs, or install packages merely to
  check whether a feature works. Follow the active task's data/API restrictions.

Network resilience methods and test commands are in
`docs/NETWORK_RESILIENCE.md`. Imports of `config.py` create directories, so
read-only tests should avoid importing the full pipeline.
