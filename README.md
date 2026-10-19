# External Theme Creator

A FreeCAD workbench for developing, testing, inspecting, applying and distributing **external UI themes**. Themes can include QSS stylesheets and related assets, SVG icon overrides, FreeCAD configuration instructions, startup scripts, and splash artwork.

> **Version 0.9.86 — cross-platform update.** Source repository: [FreeCAD-Nut/ExternalThemeCreator](https://github.com/FreeCAD-Nut/ExternalThemeCreator). This workbench has not yet been submitted to the official FreeCAD Addon Index. See the artwork notices and security notes before redistributing a modified package.

## Features

- **Develop theme** — work from a Theme Folder with independent switches for icons, QSS and its assets, configuration, and optional scripts.
- **Apply theme** — select an exported `.fctheme` package, review its license, and run with that theme.
- **Export theme** — package themes for distribution; optional author-key signing and encryption features may need additional Python packages.
- **QSS reload / Icons reload** — iterate on development theme assets without a full restart where supported.
- **CFG Instructions** — inspect/capture FreeCAD parameters and generate theme configuration instructions.
- **UI Inspector** — inspect Qt widgets and identify candidate commands and icon files.

## Compatibility

Developed and tested with **FreeCAD on Windows 11**, a **Linux x86_64 FreeCAD AppImage**, and **macOS Intel**. The maintainer also completed a testing round on **Apple Silicon** before preparing this update; detailed FreeCAD/Python/Qt version combinations and a full release test matrix are not yet recorded. Compatibility with every stable/development FreeCAD release is not guaranteed.

ETC uses FreeCAD/PySide and the Python standard library for its core workbench functions. Optional signing/encryption functionality uses `cryptography` (which may require `cffi` and `pycparser` in some environments). The confirmation-based installer supports platform-dependent FreeCAD Python environments and separates macOS Intel/Apple Silicon binary dependencies. See [security and dependencies](docs/SECURITY_AND_DEPENDENCIES.md).

## Installation

Until the Addon Index lists this workbench, install manually:

1. Close FreeCAD.
2. Copy the complete `ExternalThemeCreator/` directory into your user FreeCAD `Mod` directory. On Windows this is usually `%APPDATA%\FreeCAD\Mod\` (confirm with `App.getUserAppDataDir()` in the FreeCAD Python console).
3. Restart FreeCAD and choose **External Theme Creator** in the workbench selector.

**Important upgrade:** if your system has the old `Mod/ThemeCreator/` version installed, back it up and remove the old workbench folder before installing `ExternalThemeCreator/`. Keep your separate external Theme Folder and existing FreeCAD preferences.

The GitHub repository stores the contents of `ExternalThemeCreator/` at its top level. The downloadable manual-install ZIP wraps those files in `ExternalThemeCreator/`.

## Basic workflow

1. Prepare a separate Theme Folder. Keep user themes and their `scripts/` directory outside the addon installation folder.
2. Use **Develop theme** to point ETC to the folder and choose which assets to enable.
3. Restart into development mode to test the isolated theme, use QSS/Icons reload during iteration, and inspect the resulting UI.
4. Use **Export theme** to create a distributable theme; recipients should review the theme's license and scripts before applying it.

## Safety and privacy

ETC can launch FreeCAD subprocesses, write launch profiles/configuration, install user desktop shortcuts, execute **user-provided theme scripts**, and optionally retrieve dependencies or perform opt-in Inspector network searches. These actions are inherent to the selected feature; simply loading the workbench must not download dependencies or execute an unrelated theme. **Only apply themes from trusted sources.** See [security notes](docs/SECURITY_AND_DEPENDENCIES.md).

## Documentation

- [Release history](CHANGELOG.md)
- [Artwork credits and permissions](ARTWORK_NOTICES.md)
- [Historical development notes](docs/DEVELOPMENT_HISTORY.md)
- [Security, side effects, and optional dependencies](docs/SECURITY_AND_DEPENDENCIES.md)
- [Release and Addon Index checklist](docs/RELEASE_CHECKLIST.md)
- [Testing instructions](docs/TEST_PLAN.md)

## License

The workbench source code is licensed under **LGPL-2.1-or-later**; see [LICENSE](LICENSE). The seven original ETC command and workbench SVG icons in `Resources/icons/` are **© 2026 Vincenzo Lazzi**, licensed separately under **Creative Commons Attribution 4.0 International (CC BY 4.0)**. See [ARTWORK_NOTICES.md](ARTWORK_NOTICES.md) for the complete attribution and terms. Other graphical resources, including bundled default shortcut icons and third-party assets, have separate origins and may be subject to different copyrights and licenses. The Creative Commons license reference files in `CC_Licenses/` support theme-export licensing workflows and do not themselves license unrelated bundled assets.

## Issues and feedback

Report problems via [GitHub Issues](https://github.com/FreeCAD-Nut/ExternalThemeCreator/issues). Please include the FreeCAD version, operating system, theme launch method (Apply/Develop, Restart/shortcut), and reproduction steps.
