# Security & privacy

## What this program does

This launcher is a **fully offline, local-only** Windows application. There is no
HTTP client, no network socket, no update check, no telemetry and no analytics;
it never uploads anything. The only class imported from `QtNetwork` is
`QLocalServer` / `QLocalSocket`, which is a **local named pipe** used to wake an
already-running instance (single-instance check). It does not listen on a network
port.

It does, however, touch a few sensitive-looking areas by design. Listed here so
you can audit them:

| Area | Behaviour |
|---|---|
| Start Menu / Desktop | Reads `.lnk` shortcuts from the user and public Start Menu folders and from user and public Desktop. Only file names, targets and icons are read. |
| UWP / Store apps | Enumerates `shell:AppsFolder` through the Windows Shell COM API to obtain app names and AUMIDs. Set `AL_UWP=0` to disable. |
| Shortcut resolution | Uses the Windows Shell COM API (via pywin32) to resolve `.lnk` targets. |
| Icon extraction | Reads system image lists and caches PNGs locally. No icons are bundled in this repository. |
| Local cache | Writes `%LOCALAPPDATA%\AppLauncher\` (`meta.json`, `icons/*.png`, `custom.json`). This may contain the names and paths of applications installed on that machine. |
| Local log | Writes a rotating log to `%LOCALAPPDATA%\AppLauncher\logs\app.log`, including scan timings and uncaught exceptions. It may contain local paths and application names. |
| Single-instance IPC | Creates a local named pipe via `QLocalServer`; a second launch sends a short wake-up message to the first instance. Purely local, no network. |
| Autostart (opt-in) | `python launcher.py --autostart` creates a shortcut in the user's Startup folder. It is never enabled automatically. |
| Tray / fullscreen | Runs as a borderless full-screen window and keeps a tray icon for exiting. |
| Launching apps | Opens shortcuts with `os.startfile` (UWP apps via the `shell:` protocol), equivalent to a double-click. No elevation is requested. |

All data stays on the machine. Nothing in this repository contains user data,
local paths, logs or application icons.

To remove everything the app created:

1. Run `python launcher.py --uninstall` (removes the autostart shortcut and the
   cache; add `--keep-cache` to keep the data). **This keeps the `logs/` folder
   on purpose** for troubleshooting — delete it manually if you want a full wipe.
2. Or delete `%LOCALAPPDATA%\AppLauncher\` entirely.
3. If you enabled autostart, also remove `桌面启动器.lnk` from
   `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** (Security → Report a
vulnerability) for this repository. Do not post exploit details or personal
data in public issues. If you only have a general bug, a normal issue is fine.

When reporting, include the Windows version, Python version, PySide6 version,
and reproduction steps — but **redact your user name and any local paths** from
logs and screenshots. Never paste tokens or credentials.
