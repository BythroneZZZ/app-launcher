# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-13

First public release.

### Added

- Full-screen Windows launcher with a Steam Deck-inspired hero shelf layout.
- Scans user and public Start Menu / Desktop `.lnk` shortcuts **and** UWP / Store
  apps from `shell:AppsFolder`, resolves targets through COM, and extracts 256px
  icons plus a derived accent tint.
- Single-instance IPC over a local named pipe, rotating local log file, and an
  opt-in autostart shortcut with a matching `--uninstall` command.
- Optional PyInstaller one-dir build through `build.py`.
- On-disk metadata and icon cache with mtime-based invalidation.
- Manual add (file dialog and drag & drop), hide / restore, favourites by recent
  use, category chips, debounced search, and keyboard navigation.
- Tray icon, optional autostart shortcut, windowed debug mode, and management mode.
- Pre-rendered card faces, cached background, low-resolution glow bitmaps,
  skeleton loading cards, and three-tier animation durations.
- Qt-free logic tests (`test_logic.py`) and a manual screenshot script
  (`test_e2e.ps1`).
- Open-source paperwork: MIT license, third-party notices, contributing and
  security docs, CI workflow, and issue templates.

### Known issues

See the "Known limitations" section of `README.md`.
