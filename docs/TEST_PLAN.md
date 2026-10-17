# FreeCAD integration test plan (manual)

Record: OS, FreeCAD version/build, Python version, Qt/PySide version, build location, result, logs, and tester.

- [ ] Clean FreeCAD profile: addon load/registration, toolbar/menu labels, workbench icon, no dialogs or network on passive startup.
- [ ] Reload icon assets: separately edit ETC QSS/Icons reload SVGs; verify each updates independently.
- [ ] Develop: select Theme Folder and enable each of four asset toggles separately and in combination.
- [ ] Apply: before selecting theme, creator/tested/License Brief hidden. After Browse and acceptance, shown and enabled. Choosing another theme hides until renewed acceptance.
- [ ] Create/relaunch themed session and shortcut; ensure user choices persist. Validate existing shortcuts after upgrade.
- [ ] QSS reload and icons reload: modified assets apply without losing custom FreeCAD toolbar layout.
- [ ] UI Inspector: widget finding, icon identification, optional online search disabled by default.
- [ ] CFG instructions: capture/edit/export; validation; no unexpected global configuration modification.
- [ ] Export/import `.fctheme`; license acceptance; test bad/corrupt/path-traversal archives safely.
- [ ] Explicitly accept/install cryptography dependencies and reject; verify no automatic install on ordinary workbench launch; verify downloaded packages before install.
- [ ] Theme script execution and reload: opt-in behavior, script errors isolated, lifecycle and cleanup.
- [ ] Close/relaunch, interrupted restart, uncaught errors, missing assets, permissions, no orphan helpers.
- [ ] Manual install, GitHub Addon Manager install/update/removal and residual user data.
- [ ] FreeCAD latest stable + dev, Windows/macOS/Linux only when claiming compatibility.
