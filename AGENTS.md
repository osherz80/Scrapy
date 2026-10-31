# Scraper workspace rules

- User update (2026-10-31): local CLI launches and migration administration may
  load the scraper-root `.env` automatically through the dedicated environment
  bootstrap. Never display/dump its contents, credentials or environment mapping.
  Do not manually inspect secret files or search parent folders for them. Process
  variables take precedence; explicitly injected mappings bypass file loading.
  Test database fixtures still require process TEST_DATABASE_URL and must never
  obtain a database target from `.env` or fall back to production DATABASE_URL.
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
