# Changelog

## 0.9.86 — Cross-platform launch and theme handling (2026-10-18)

- Port Linux-validated Apply Theme, Develop Theme, packaged script loading, workbench discovery, and AppImage restarts/shortcuts to the consolidated workbench.
- Improve Linux AppImage executable discovery, child-process environment cleanup, user workbench linking, and selective handling of development `.cfg` files.
- Improve FreeCAD application-bundle and bundled-Python detection for macOS Intel and Apple Silicon, with architecture-separated private `cryptography` dependencies.
- Correct macOS application shortcut preparation, protected-folder access, command quoting, and persistent Apply Theme package snapshots.
- Preserve live development QSS, icons, scripts, and configuration while preparing macOS Develop Theme shortcut launch data; document its shortcut-specific configuration snapshot.
- Consolidate macOS FreeCAD startup macros, native-splash suppression, custom splash shutdown, and splash helper Dock behavior.
- Launch macOS FreeCAD via its application bundle rather than a bare `exec` process, including the detached Develop Theme Restart helper.
- Restore theme-specific macOS Dock icons in Apply/Develop Restart and desktop shortcut flows.
- Preserve separate Apply Theme and Develop Theme runtime behavior, settings persistence, licensing, and theme startup scripts.

The macOS Intel launch paths and Linux AppImage workflows were exercised during testing. Apple Silicon testing was also completed by the maintainer; detailed per-platform FreeCAD/Python/Qt build information is not included in this release history. This update is not equivalent to a comprehensive security audit or an official FreeCAD Addon Index approval.

## 0.9.85 — GitHub release candidate (2026-10-17)

- Set `ETC_export.svg` as the FreeCAD workbench selector icon and `package.xml` icon.
- Removed the unused placeholder workbench icon.
- Added explicit SVG copyright attribution (`© 2026 Vincenzo Lazzi. All rights reserved.`); separate redistribution permission remains to be confirmed before publication.
- Kept the README generic and deferred screenshot addition and live testing until GitHub publication.
- No intentional changes to theme handling, command behavior, or selection rendering.

## 0.9.84 — release candidate (2026-10-17)

- Incorporated seven maintainer-supplied SVG icons for Apply, CFG, Develop, Export, Inspector, QSS Reload, and Icons Reload.
- Removed obsolete `ETC_reload.svg`, retaining distinct QSS and Icons reload filenames.
- Added workbench icon path and Addon Manager icon metadata.
- Completed metadata namespace, name, tags and license-file reference; repository URL intentionally remains pending until confirmed.
- Removed compiled Python cache files from distribution and supplied GitHub `.gitignore`.
- Prepared public-facing README, preserved development history, and added security, test, release and license review checklists.
- Updated historical project name and provisional copyright attribution in LICENSE; LGPL 2.1 license text retained unchanged.
- No intentional changes to theme creation, application, export, or launch logic.

## 0.9.83

- Apply theme hides creator/tested version metadata and License Brief until the selected theme's license is accepted.

## 0.9.82

- Corrected live Icons/QSS reload mapping for separately named `ETC_reload_icons.svg` and `ETC_reload_QSS.svg`.

For older release notes, see [development history](docs/DEVELOPMENT_HISTORY.md).
