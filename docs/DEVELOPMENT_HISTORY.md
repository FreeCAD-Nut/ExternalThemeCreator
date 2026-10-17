# External Theme Creator v0.9.83

## v0.9.83
- Apply theme hides creator/tested version metadata and License Brief until the selected theme license is accepted. The dialog collapses to its compact initial height and expands upon acceptance.

## v0.9.82
- Fixed Icons reload live-command lookup for the two independent reload icons. QSS reload maps to `ETC_reload_QSS.svg`, while Icons reload maps to `ETC_reload_icons.svg`; the live reload mapping no longer points to the removed shared `ETC_reload.svg`.


- QSS reload uses `Resources/icons/ETC_reload_QSS.svg`; Icons reload uses its own `Resources/icons/ETC_reload_icons.svg`. The icons have identical initial artwork but are independently editable. UI Inspector filename alias for Icons reload updated.


- The installed workbench folder is now `ExternalThemeCreator/`. Renamed the Python modules, FreeCAD command IDs, workbench class, and bundled resource file to use the same identity.
- Retained legacy data migration for existing settings and development runtime; renamed generated launcher files and user-facing outputs.
- **Upgrade:** close FreeCAD, remove the previous `Mod/ThemeCreator/` installation after backing it up, install `Mod/ExternalThemeCreator/`, then create a fresh desktop shortcut. Do not delete the existing Theme Folder or its top-level CFG.
- Previous command IDs are not registered under the new names; users with custom FreeCAD toolbars referencing old IDs should update those references.


- Migrates legacy launcher settings and development runtime to the new External Theme Creator naming. Old state is retained as backup; new profiles are not silently merged. Recreate shortcuts after removing the former workbench installation folder.


- Renamed the user-facing workbench, toolbar, dialogs, runtime prompts, and documentation to External Theme Creator.
- Renamed the workbench installation root, Python modules, command IDs, and package metadata. Migration retains legacy settings and runtime folders as backups.

# External Theme Creator v0.9.67

- Windows developer desktop shortcut: launch FreeCAD with `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` rather than `DETACHED_PROCESS`. Direct the child's standard handles to DEVNULL. This prevents Windows Terminal from hosting a transient `Develop` console for console-subsystem FreeCAD development builds.
- No changes to Restart with theme, the splash rendering/handshake, or the theme configuration.

# External Theme Creator v0.9.65

- Splash respects the active FreeCAD `.cfg` ShowSplasher preference, not the JSON instructions. The replacement splash uses a launch-only native suppression override and never writes ShowSplasher into the CFG. Removed the obsolete splash warning/version checkbox.

- Explicit `ShowSplasher=0` in `theme-configuration.json` now disables the custom startup splash for both Restart with theme and creator desktop shortcuts, in addition to FreeCAD's native splash.
- An active CFG containing `ShowSplasher=0` also disables the replacement when that value was not set by External Theme Creator's own native-splash suppression marker.
- The marker distinguishes the automatic suppression required while the replacement splash runs from a user-provided disabled preference. A JSON instruction takes priority even when a marker exists.
- The existing "Suppress splash warning and version" option remains relevant only to FreeCAD's native-splash fallback, not to the External Theme Creator replacement splash.

# External Theme Creator v0.9.61

- Detached Restart with theme helper now loads a dedicated lightweight splash controller rather than importing the entire application launcher (which can fail on FreeCAD 26.3 SSL).
- Desktop shortcut launcher writes an early-entry diagnostic before loading network libraries, including on interpreter errors later in startup.
- SSL is imported only inside the network functionality that uses it.
- Both startup paths continue to retain the native splash fallback when the replacement helper cannot run.

# External Theme Creator v0.9.18


## v0.9.18 shortcut honors saved Develop-theme options

- Develop theme → Create shortcut now launches with `--launch-as-creator`, not the forcing `--launch-as-creator-all` switch.
- The shortcut dynamically loads the latest saved settings every time it is opened; changes to the four asset checkboxes require no shortcut recreation.
- Older v0.9.16 shortcuts with `--launch-as-creator-all` are also interpreted as a normal saved-settings launch for backward compatibility.
- Packaged-theme/user shortcuts remain unchanged.

## v0.9.16 independent Develop-theme assets

- Four independent persistent creator launch options: external icons, stylesheet/assets,
  configuration, and UI scripts.
- Disabled stylesheet mode bypasses QSS and splash injection; disabled configuration
  mode bypasses theme CFG and JSON layout operations.
- Icons-only runs without injecting an isolated FREECAD_USER_HOME; theme icons
  remain available through FreeCAD's external icon environment variables.
- Disabled external icons are explicitly removed from the child environment.
- Settings are preserved in launcher settings across launches and restarts.

## v0.9.15 native 1:1 splash source rendering

- Removed External Theme Creator's generated 2x splash-image upscaling and smooth resampling.
- The selected splash PNG is now passed directly to FreeCAD, byte-for-byte unchanged; External Theme Creator does not create a resized splash copy.
- Splash artwork size is therefore controlled by the actual pixel dimensions of the PNG supplied by the theme creator.
- Old `theme_splash@2x.png` and `prepare_hidpi_splash.py` runtime artifacts from v0.9.12 are cleaned up automatically when a theme is launched.
- The existing **Suppress splash warning and version** option is unchanged.


## v0.9.12 splash controls and HiDPI splash rendering

- Added **Suppress splash warning and version** to **Apply theme → Settings** and **Develop theme → Settings**. It is enabled by default.
- Suppression is applied at FreeCAD launch time, before the splash is painted; no theme runtime script is required.
- Custom splash images now use a DPI-aware launch path instead of the legacy `images:splash_image.png` override.
- External Theme Creator prefers a theme-provided `@2x` companion PNG when present; otherwise it generates a smooth-resampled 2x runtime copy when Qt or Pillow image support is available, then points FreeCAD to the `@2x` asset.
- Legacy runtime splash copies from older External Theme Creator versions are removed so they cannot override the new HiDPI splash path.

## v0.9.11 capture color swatch positioning

- Added `SWATCH_X_OFFSET = 6`; the 18x18 capture color swatch is painted 6 logical pixels farther right while retaining the 1-device-pixel cosmetic border, 3 px radius, and 20x20 icon slot.

## v0.9.10 capture color swatch rendering

- Capture color previews are still 18×18 px with 3 px rounded corners in a 20×20 px QList icon slot.
- The swatch is now painted directly by a QStyledItemDelegate instead of being pre-rendered into a QPixmap/QIcon.
- The border uses a zero-width cosmetic QPen, which Qt renders as one physical device pixel regardless of display/DPI scaling.
- The transparent icon remains only as a 20×20 layout placeholder so text alignment and the existing click target are unchanged.


- External Theme Creator command stubs are now registered as soon as `InitGui.py` loads, instead of waiting for the External Theme Creator workbench to be activated.
- The heavy `ExternalThemeCreatorCommands` implementation remains lazy and is still imported only when a External Theme Creator command is actually activated.
- This allows FreeCAD to resolve External Theme Creator commands while rebuilding custom toolbars owned by other workbenches, avoiding the case where a saved External Theme Creator action is reconstructed at the end of the toolbar instead of at its saved position.
- Workbench toolbar/menu creation remains deferred to `ExternalThemeCreatorWorkbench.Initialize()`.

## v0.9.8 semantic dock-tab layout

- Added the portable runtime-only `tabify_docks` instruction for `ui.layout`.
- `tabify_docks` is now accepted by **Validate CFG instructions (.json)** and is no longer reported as an invalid instruction action.
- The action is deliberately excluded from generated FreeCAD CFG XML because dock tabification is a live Qt main-window operation, not a FreeCAD parameter value.
- At themed FreeCAD startup, External Theme Creator reads semantic layout instructions and runs a startup macro that finds the requested `QDockWidget` objects and calls `QMainWindow.tabifyDockWidget()`.
- The runtime prefers stable Qt object names and falls back to visible dock titles/case-insensitive matches. Current FreeCAD source uses object names `Model` and `Tasks`, so `{"action":"tabify_docks","primary":"Model","secondary":"Tasks","active":"Model"}` is supported directly.
- The semantic layout macro is generated for both Creator launches and packaged-theme launches through External Theme Creator's bundled external theme runtime.
- When **Use external configuration (.cfg)** is disabled in Develop Theme, semantic configuration actions are disabled with it.
- Startup re-applies the tabification briefly during initialization so later workbench/dock restoration does not immediately undo it.



## v0.9.7 portability-validator refinement

- Reworked OS/user dependency detection so filesystem paths are recognized with boundary-aware Windows, macOS, and Linux patterns instead of normalizing every slash.
- Fixed the false positive where Base64/Qt `MainWindowState` data containing `////` could be mistaken for a Windows UNC path.
- `MainWindowState` and similar opaque Qt/FreeCAD state are now reported separately as **Serialized UI state**, with an explanation that they may depend on FreeCAD/Qt versions, available dock widgets/toolbars, or screen/layout context, but are not OS filesystem dependencies.
- OS-specific findings now identify the actual dependency type, such as Windows drive path, UNC/network path, Windows user profile/AppData, environment-variable dependency, macOS user-home/system path, Linux user-home path, temporary directory, or Unix/Linux system path.
- CFG validation uses the same improved distinction, so large serialized state is no longer mislabeled as a filesystem path.

FreeCAD External Theme Creator workbench.

## Develop theme changes

- **Advanced** is renamed to **Settings**.
- `FREECAD_USER_HOME` runtime isolation is always enabled and is always created inside `<Theme Folder>/.ExternalThemeCreator_runtime/`.
- Restart always closes the current FreeCAD session before starting the themed session.
- The External Theme Creator dialog always closes when launching FreeCAD.
- **Apply now** is hidden from Develop theme; use **Restart with theme** for an authoritative theme test.
- New settings:
  - **Use external theme stylesheet (.qss) and assets** — default enabled. Uses the top-level QSS and the standard `qss-assets/` subfolder.
  - **Use external configuration (.cfg)** — default enabled. When disabled, the Theme Folder CFG is ignored and the normal system-user FreeCAD CFG is used.
  - **Use external UI scripts** — default enabled. Loads Python files from the standard `scripts/` subfolder.
- **Create shortcut** always launches Creator Mode with all theme assets enabled.

## Theme runtime scripts

Creator Mode loads optional Python scripts from `<Theme Folder>/scripts/`. Script errors are isolated and nonfatal. Two known scripts have explicit lifecycle hooks:

- `property_editor_no_grid_v8.py` → `nut_grid_install()` / `nut_grid_uninstall()`
- `task_header_arrows_v10.py` → `nut_task_arrows_install()` / `nut_task_arrows_uninstall()` / `nut_task_arrows_reload()`

Other `.py` files in `scripts/` are executed as optional theme scripts. Conventional `theme_install`/`install`, `theme_uninstall`/`uninstall`, and `theme_reload`/`reload` hooks are honored when present.

QSS Reload performs a clean script uninstall/reload/install cycle. Icons Reload calls script artwork reload hooks so externally edited assets can refresh in the current session.

## Standard Theme Folder subfolders

```text
Theme Folder/
    qss-assets/
    scripts/
    .ExternalThemeCreator_runtime/
```

The workbench itself is packaged inside the top-level `ExternalThemeCreator/` directory in the release ZIP.


## v0.8.1 CFG Instructions updates

- Old CFG and New CFG fields accept drag-and-drop `.cfg` files from the OS file manager.
- Skipped/captured instructions no longer include per-item `reason` fields.
- Added **Validate CFG** beside Start/Stop capture. It checks XML syntax/structure, duplicate groups/parameters, typed values, unsupported node types, configured CFG ambiguity, OS/user-specific paths, transient settings, embedded stylesheet data, and large serialized values.
- Validation findings are separated into errors, warnings, and portability notes.

## v0.9.0 Apply-theme runtime + CFG Instructions redesign

- Apply theme → Settings now includes a user-selectable **Theme runtime location**. The default is the operating system temporary directory used by packaged-theme launches.
- CFG Instructions now places the instructions filename at the top and separates compare/generate, blank generation, JSON validation/organization, and CFG validation/organization into dedicated workflows.
- Compare fields support drag-and-drop. Existing `theme-configuration.json` / `theme-configuration-skipped.json` files are protected from accidental overwrite.
- Capture results are displayed as selectable instruction blocks with multi-selection (Ctrl) and range selection (Shift), and selected blocks can be appended to `theme-configuration.json`.
- JSON validation detects malformed structure, duplicate targets, invalid actions/fields, and portability dependencies, then normalizes section/instruction ordering.
- CFG validation keeps order-sensitive toolbar parameters intact while organizing safe group sections and normalizing XML formatting.

## v0.8.3 Apply theme updates

- **Advanced** is renamed to **Settings** in Apply theme.
- Removed **Apply now**. Packaged themes are applied by **Restart with theme** or **Create shortcut**.
- Removed the separate **License notice** button. The packaged license notice is displayed automatically in the Apply theme window when a valid `.fctheme` file is selected or dropped.
- The **Theme file** field accepts drag-and-drop `.fctheme` files from the OS file manager.
- Packaged-theme Settings no longer expose external-icon or extra command-line argument controls. Packaged themes always launch with all available packaged assets enabled and with no user-specific extra CLI arguments.
- Packaged-theme Settings no longer show Theme Configuration Diagnostics, the external-icon reload-command control, or the old information/status text area.


## v0.9.1 CFG filename + capture fix

- Fixed the real-time CFG capture bridge (`generate_cfg` was missing in v0.9.0).
- Added **CFG filename (.cfg)** directly under **CFG instructions filename (.json)**.
- The CFG filename is persisted as the Creator CFG filename and written to `theme-configuration.json` as `output.filename`.
- Blank generation, comparison generation, capture, and adding captured blocks all use the same authoritative CFG filename.
- When the configured CFG is missing at launch, External Theme Creator uses this filename when generating the new Theme Folder CFG from `theme-configuration.json`.


## v0.9.2 capture-list editing

- Added **Clear captured** beside Start/Stop capture. Stop/start cycles retain captured blocks; Clear is explicit.
- Added capture-list right-click **Copy** for one block or the current multi-selection.
- Color-valued instructions show a rounded color swatch; clicking it opens the native Qt color picker and updates the in-memory instruction before copy/add.
- Capture results now merge into the existing list across capture cycles, updating an existing target rather than clearing the terminal.

## v0.9.3 interactive CFG-instructions validation

- `Validate CFG instructions (.json)` now opens an interactive issue list instead of a plain text report.
- Every validation problem is a selectable row showing severity, section/block number, target, and a human-readable explanation of why it is problematic.
- Selecting a row shows the exact JSON instruction block in a read-only preview pane.
- Instruction-level problems include a `Delete` button that removes that block directly from `theme-configuration.json` after confirmation.
- Duplicate-target problems show the earlier duplicate as a child row with its own `Delete` button, so the creator can choose which side of the duplicate pair to remove.
- Global/schema problems remain visible but are intentionally not deletable because they do not correspond to one instruction block.
- After a deletion the file is revalidated immediately and the issue list refreshes.
- Duplicate explanations distinguish exact duplicates from case-only target differences and other normalized-target conflicts.


## v0.9.4 capture add/update behavior

- Add selection now updates an existing exact instruction target when the captured value/data differs.
- Exact existing instructions with identical data are skipped.
- Case-only target differences, multiple normalized matches, and conflicting actions remain blocked as duplicates/conflicts.
- Capture color swatch remains 18x18 px canvas, 16x16 px visible rounded square, 1 px border, 3 px radius, in a 20x20 px icon slot.


## v0.9.6 validation repair and captured-value editing

- Validate CFG instructions now attempts conservative automatic repair of minor JSON punctuation errors (currently missing commas between adjacent values/blocks and trailing commas). The original malformed file is saved beside it as a numbered `.bak` file before the repair is written.
- Captured `set` instruction values can be edited before adding them to `theme-configuration.json` by double-clicking a block or using right-click → Edit value. Standard FreeCAD numeric/bool types are validated before accepting the edit.
- Color swatches now use a 20×20 raster/icon slot with an 18×18 visible rounded square, 1 px border, and 3 px radius.

## Theme Folder layout (v0.9.15)

Keep the top-level `.qss`, `theme-configuration.json` and configured `.cfg` at the Theme Folder root. Asset folders:

- `icons/` — custom theme icons, including `preferences-sketcher.svg`
- `license/License.lic` — theme license
- `qss-assets/` — stylesheet resource files
- `scripts/` — optional runtime Python scripts
- `shortcut-icon/Custom_Icon.icns`, `.ico`, `.png` — OS shortcut icons
- `splash/freecadsplash.png` — native-resolution splash PNG (no interpolation)

Theme export keeps these relative paths inside encrypted packages.


## Export Theme (v0.9.18)

Export always creates a complete, self-contained `.fctheme` archive. External asset URL selection and artwork-only exports are no longer offered. The exporter includes the License and License Brief metadata only; legacy readers remain compatible with older packages containing notices. The FreeCAD license dropdown choice is LGPL (LGPL-2.1-or-later terms); select it only when appropriate for the content you distribute. For Custom License, put `License.lic` and `License-brief.lic` inside the theme's `license/` folder; the brief is imported into the editor and stored in the manifest, not packaged as a second license document.

### Optional cryptography dependency
Signed-theme export and Author Keys require the external `cryptography` Python package. If missing, External Theme Creator prompts before installing it from PyPI into a version-specific folder under the current user's profile. This requires an internet connection and a FreeCAD-compatible Python interpreter with pip; nothing is installed into the FreeCAD application directory. For security and compatibility, native binary wheels are not copied blindly between Python versions.


### v0.9.22
- Export summary counts only `theme-configuration.json` under Configuration instructions (.json); skipped review JSON is excluded.
- Packaged Apply theme restart uses the SSL-compatible ExternalThemeCreatorRuntime bridge instead of importing the full application launcher directly in FreeCAD Python.
- Restart helper captures the child launch output in the runtime log to diagnose failures.

### v0.9.24
- Apply theme shortcut now launches the SSL-safe ExternalThemeCreatorRuntime.py bridge rather than ExternalThemeCreatorLauncher.py directly.
- Apply theme displays creator and tested FreeCAD versions from signed package metadata and halves the License Brief height. Earlier packages without creator metadata show Not recorded.
- Export theme: Launcher Compatibility renamed External Theme Creator Compatibility. Newly exported manifests record theme_creator_version.

### v0.9.25
- Apply theme: exact 30 px above / 10 px below License Brief label; compact dialog height.
- License acceptance validates private cryptography signing/encryption before allowing Restart or Create shortcut. First inspection of an encrypted package may still prompt for dependency installation before the license can be displayed.
- Both launch paths continue to prepare the target runtime Python environment when required.

### UI Inspector (v0.9.28)

Activate External Theme Creator → UI Inspector. Hover over a Qt control and press Ctrl+Shift+I
(or press Capture now when the mouse is over the target). Live mode updates the
reading every 250 ms; close the dialog to stop all hooks and sampling.
The inspector is read-only and does not alter widget styles or FreeCAD settings.
QSS matches are *possible selectors* only; Qt does not expose the computed cascade.
The connection between a widget and FreeCAD CFG/JSON parameters cannot generally
be determined automatically, so it is reported as unknown, not "FreeCAD default".
Viewport geometry and custom-painted subcontrols need separate specialized inspectors.

UI Inspector: the capture shortcut is editable by clicking the shortcut field and pressing a key combination; it persists in FreeCAD parameters. Capture in 3 s allows time to move the pointer after clicking. Live mode updates continuously without adding capture history.


### v0.9.29 — UI Inspector startup fix

Initialize the saved shortcut before constructing the Inspector dialog to prevent a missing attribute exception when clicking its workbench command.

### v0.9.32 — UI Inspector shortcut and report refinements

- Use Qt application shortcut registration for capture; suspend it while editing the shortcut.
- Shorten the QSS/CFG tab, remove duplicate selector candidate from Widget report.
- Add explicit alternating report row colors and color-value preview swatches.

### v0.9.33 — UI Inspector window and report spacing
- Inspector is always on top without a checkbox, uses standard dialog window controls matching CFG Instructions, and removes gaps between alternating report rows.

### v0.9.36 — Inspector icon origin and default width

- Set inspector initial width to 1140 logical pixels.
- Display icon source only when an actual path or Qt theme/resource name can be recovered; otherwise show an honest unknown-source diagnostic.

### v0.9.37 — UI Inspector command-first icon lookup and delayed progress

- Prioritize FreeCAD command IDs from QAction metadata and command tooltip identifiers when searching active theme icons. Preserve visual matching as an unverified fallback.
- Display command ID and icon-source classification in the Widget report.
- Show inspection progress only after a 500 ms delay, and hide it on completion.

### v0.9.38 — UI Inspector startup capture and source lookup
- Avoid shortcut-recorder focus stealing the first capture after opening the Inspector.
- Inspect command-named Qt resource locations before fallback pixel comparison.
- Show a GitHub source-code search URL for an unresolved command, clearly marked as a lookup rather than a confirmed file.

### v0.9.41 — UI Inspector optional online icon lookup

Adds an opt-in Allow online search toggle, asynchronous public FreeCAD source-index query, and a 500 ms delayed progress indicator. No GitHub account is required.

### v0.9.41 — UI Inspector icon naming and core resource mapping

- Removed GitHub command search from Widget report.
- Icon file shows filename before full path.
- Added source-derived mappings for FreeCAD core structure commands (including Std_Part → Geofeaturegroup).

### v0.9.42 — UI Inspector Widget report field order

- Place Icon file, Icon source and Icon size directly after Text, followed by Tooltip.
- No changes to capture or icon-identification logic.

### v0.9.43 — Isolated FreeCAD launch profiles

- Normal FreeCAD continues to use the native configuration.
- Applied .fctheme packages use a persistent per-theme user home alongside their persistent CFG.
- Develop theme always uses its own user home and private writable user.cfg, even with all asset switches disabled.
- On first development launch, a Theme Folder CFG is copied into the private profile; if absent, normal FreeCAD configuration is copied and theme-configuration.json is applied to the private copy.
- When external configuration is disabled, the development profile is initialized from normal configuration without applying theme configuration.
- Existing development profile settings are preserved on subsequent launches; delete development_profile/user.cfg to reinitialize from the inputs.


Version 0.9.44: Develop theme adds a native-size splash preview and a Theme Folder template creator.

Version 0.9.45: Develop theme has a two-column, three-row equal-width button grid; splash preview toggles Display/Hide; new Theme Folders include a root README.txt covering QSS, CFG, JSON and isolated development runtime.

Version 0.9.46: Develop theme buttons no longer accept initial keyboard focus; Create Theme Folder does not change Settings; one root-level .cfg is the persistent isolated development configuration (no duplicated development_profile/user.cfg); root README explains exact startup splash-preview differences and runtime.

Version 0.9.47: Captured CFG instructions can create theme-configuration.json on first Add selection; generated root README documents the operation and automatic runtime-folder exclusion during export.

Version 0.9.48: Theme Folder README documents compare/generate CFG instructions; generator explicitly protects existing JSON instructions; splash preview uses Qt QSplashScreen at native PNG dimensions.

Version 0.9.49: Display splash accounts for monitor device pixel ratio to preserve original PNG physical pixel dimensions without resampling.

Version 0.9.50: Fix splash preview clipping at high-DPI scaling by removing the physical-pixel QWidget mask, using alpha transparency, and sizing the QSplashScreen in device-independent units.

Version 0.9.51: optional separate Qt launch splash helper with native source pixels; suppresses the built-in splash in the isolated theme CFG when helper is running.

Version 0.9.52: Startup splash helper explicitly enables Windows per-monitor DPI awareness before initializing Qt, checks effective monitor DPI, and saves DPI diagnostics in its runtime folder.

Version 0.9.53: Persistent splash-startup.log and splash-helper.log diagnose interpreter detection, process startup, Qt failures, helper readiness, and native fallback.

Version 0.9.54: Fix Develop theme Restart with theme to launch the native-resolution splash from its detached restart helper, with persistent diagnostics and native splash fallback.

Version 0.9.55: Fix restart-helper undefined timer and window-detection function; parent-stage splash diagnostics now persist before FreeCAD exits.

Version 0.9.56: Add persistent desktop-shortcut launch diagnostics before headless initialization, trace resolved theme launch settings and startup splash fallback, and verify splash helper remains alive when it signals readiness.

Version 0.9.59: Locate bundled FreeCAD Qt platform plugins for the standalone splash helper and set QT_QPA_PLATFORM_PLUGIN_PATH for both desktop-shortcut and development-restart launches. Log plugin discovery and preserve native splash fallback when unavailable.

Version 0.9.59: Locate the Qt Windows platform plugin in FreeCAD installations using <FreeCAD>/lib/qt6/plugins/platforms/qwindows.dll, while retaining alternative layout checks. Applies to both shortcut and Restart with theme launch paths.

Version 0.9.61: Fix Windows splash helper readiness-file sharing errors, clean up failed helpers before native fallback, and correct ShowSplasher XML preference path when absent. Shortcut splash diagnostics retained.

Version 0.9.61: Enable custom native-resolution startup splash for development desktop shortcuts (ExternalThemeCreatorRuntime creator launch), with readiness monitoring and shortcut diagnostics.

### v0.9.67
- Windows desktop shortcut: launch FreeCAD with DETACHED_PROCESS, matching the proven console-free restart path; preserve other runtime and splash behavior.
