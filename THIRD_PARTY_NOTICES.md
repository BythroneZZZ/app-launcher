# Third-party notices

The source code in this repository is licensed under the MIT License (see `LICENSE`).
The following libraries are **runtime dependencies only** — they are installed by the
user with `pip` and are **not redistributed** in this repository.

| Dependency | License | Notes |
|---|---|---|
| [PySide6 (Qt for Python)](https://doc.qt.io/qtforpython-6/) | Community edition: LGPLv3 / GPLv3 (a commercial edition is also available) | Installed via `pip install PySide6`. Refer to the [Qt licensing page](https://www.qt.io/licensing/) for the authoritative terms. |
| [pywin32](https://github.com/mhammond/pywin32) | PyPI metadata declares PSF-2.0; upstream states the project contains a mix of licenses and that the license files in its source tree are the source of truth | Only the COM bindings (`pythoncom`, `win32com`) are used. |
| [PyInstaller](https://pyinstaller.org/) (optional) | GPLv2 with bootloader exception | Build-time tool only, used by `build.py` to produce a standalone Windows executable. Not a runtime dependency and not bundled in this repository. |

## If you redistribute a bundled build

This repository ships source code only. If you build a self-contained Windows
executable (for example with PyInstaller) and distribute it, you bundle the Qt
libraries and therefore must comply with LGPLv3 yourself, which typically means:

- including the LGPLv3 / GPLv3 license texts and attribution,
- allowing the recipient to replace the Qt libraries with a modified version,
- not imposing additional restrictions on the Qt portion.

The MIT license of this project does not override the licenses of its dependencies.

## Application icons

Icons shown by the launcher are extracted at runtime from the user's own local
shortcuts and cached under `%LOCALAPPDATA%\AppLauncher\icons\`. No third-party
icons or trademarks are included in this repository. Screenshots in issues or
documentation may incidentally show third-party application icons; those
trademarks belong to their respective owners and are used for identification
only.
