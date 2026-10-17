# Publication and FreeCAD Addon Index checklist

## Prepared in this candidate

- [x] Traditional FreeCAD workbench at repository root: `Init.py`, `InitGui.py`, `package.xml`.
- [x] Icon resource added to package metadata and FreeCAD workbench class.
- [x] Seven updated SVGs incorporated; separate icons for QSS and Icons reload.
- [x] README, changelog, security notes, test plan, `.gitignore` created.
- [x] Python bytecode and XML/SVG static validation, as reported by local build script.

## Before creating the public repository

- [ ] Confirm redistribution permission for artwork labeled `© 2026 Vincenzo Lazzi. All rights reserved.` and bundled shortcut assets. Verify code author attribution.
- [ ] Create a public GitHub repository; then insert its real `<url type="repository" branch="main">…</url>` in package.xml and update README links.
- [ ] Confirm maintainer contact information (email optional if maintainer chooses not to expose it publicly).
- [x] Use `ETC_export.svg` for both the workbench selector and Addon Manager icon.
- [ ] Add screenshots after the initial GitHub publication (before Addon Index request).
- [ ] After GitHub publication: test clean repository installation, manual ZIP installation, updating and removal.
- [ ] Test FreeCAD latest stable, development build, Windows, Linux, macOS, Qt5/Qt6 combinations where compatibility is claimed; update README based on facts.
- [ ] Complete security review of import/extraction, optional dependency bootstrap, arbitrary user-provided theme scripts, startup actions, and file deletion paths.
- [ ] Before Addon Index request: have external users exercise the addon and record reproducible results.
- [ ] Publish repository publicly; postpone Addon Index request until the review and testing gates are satisfied.

## Submission

Official guide: https://freecad.github.io/Addon-Academy/Guides/Publishing/Indexed

1. Publish the actual addon repository, with `package.xml` at repository top level and the source visible.
2. Run clean-addon installation tests, then publish a candidate/tag after checks.
3. Open **Addon - Addition** issue: https://github.com/FreeCAD/Addons/issues/new/choose (follow current issue template and instructions).
4. Respond to reviewers; publish a new approved tag when requested. An initial PR should **not** be assumed mandatory with the modern Addon Index.
5. Normal future addon code changes happen in your own repository; FreeCAD reviewers may require an Index update only for metadata or policy changes.
