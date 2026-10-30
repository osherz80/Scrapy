# Scraper workspace rules

- Never read `.env` or other secret environment files, directly or indirectly
  through tools, subprocesses, dotenv, or test helpers. Assume supplied settings
  exist. Use explicitly supplied process environment; never print secret values.
  Report concrete missing inputs after completing independent work.
- Keep all file operations inside this scraper project. Use root `Temp/` for
  temporary files, downloads and caches, and clean task-created files afterward.
  Keep installed runtimes/virtual environments in ignored local directories.
  Runtime installers must disable user/global executable shims and registration.
- Follow `SPEC-supermarket-scraper.md` and the execution state in `tasks/todo.md`.
  Work sequentially in tested commits; do not claim untested provider coverage or
  database/hosted readiness. Scope is the scraper only.
- Use Python 3.12. Verification and local cache configuration are documented in
  `README.md`. Never merge, deploy, incur cost or change sampling/retention rules
  without the corresponding user authorization.
