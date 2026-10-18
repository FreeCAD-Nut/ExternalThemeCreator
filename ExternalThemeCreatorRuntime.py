"""External Theme Creator bridge based on the bundled launcher engine 1.52.15 runtime.

ExternalThemeCreatorLauncher.py is bundled as the compatibility base and includes small
External Theme Creator launch extensions where needed (including splash handling).
This bridge adds the headless entry points needed by the FreeCAD workbench.
All theme preparation, Theme Folder CFG handling, .ExternalThemeCreator_runtime layout,
QSS startup application, icon environment, splash handling, package handling,
shortcut generation, and diagnostics are delegated to the bundled launcher.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import types

# Desktop shortcuts launch a fresh Python process. Unlike the FreeCAD workbench
# restart/create-shortcut path, that process does not inherit the dependency
# installer's temporary PYTHONPATH changes. Register the same private,
# version-specific dependency directory before the bundled launcher needs cryptography.
# This is read-only activation: no downloads, installation, or FreeCAD changes.
import ExternalThemeCreatorDependencies as _tc_private_deps
_tc_private_deps.activate()


def _load_ui_launcher_without_network_stack():
    """Load the bundled legacy launcher source while avoiding FreeCAD's broken ssl module.

    FreeCAD 26.3's embedded Python can fail importing stdlib ssl because its ssl.py
    expects RAND_pseudo_bytes while the bundled _ssl.pyd does not expose it.  The
    Creator launch/build path does not use networking, so keep the original Launcher
    source and behavior but omit only the two network imports that trigger ssl.
    Network-dependent Launcher functions remain unavailable inside the FreeCAD
    process and should be run through an external helper if needed.
    """
    source_path = Path(__file__).with_name("ExternalThemeCreatorLauncher.py")
    source = source_path.read_text(encoding="utf-8")
    source = source.replace("from urllib import request as urllib_request\n", "urllib_request = None  # disabled in FreeCAD embedded runtime\n")
    source = source.replace("import ssl\n", "ssl = None  # disabled in FreeCAD embedded runtime\n")
    module = types.ModuleType("ExternalThemeCreatorLauncherCompat")
    module.__file__ = str(source_path)
    module.__package__ = ""
    sys.modules[module.__name__] = module
    exec(compile(source, str(source_path), "exec"), module.__dict__)
    return module


UIL = _load_ui_launcher_without_network_stack()

# External Theme Creator capture extension: UI appearance controls are not confined to
# Preferences/View. FreeCAD stores some color/font/highlight settings under
# other Preferences branches. Preserve the legacy launcher's conservative classifier,
# but recognize clearly visual parameters anywhere under Preferences except
# known modeling/document/workbench branches.
_original_theme_ui_category = UIL._theme_ui_category

def _theme_creator_ui_category(parameter):
    category = _original_theme_ui_category(parameter)
    if category:
        return category
    path_l = str(parameter.get("path", "")).lower()
    name_l = str(parameter.get("name", "")).lower()
    if "/preferences" not in path_l:
        return None
    non_ui_paths = (
        "/preferences/units", "/preferences/document", "/preferences/import",
        "/preferences/export", "/preferences/objects", "/preferences/part",
        "/preferences/sketch", "/preferences/mesh", "/preferences/draft",
        "/preferences/mod/",
    )
    if any(token in path_l for token in non_ui_paths):
        return None
    appearance_tokens = (
        "color", "colour", "background", "foreground", "font",
        "highlight", "selection", "textsize", "iconsize",
        "markersize", "linewidth", "pointsize", "transparency",
        "shininess", "contrast", "palette", "accent", "crosshair",
        "axis",
    )
    if any(token in name_l for token in appearance_tokens):
        return "appearance"
    return None

UIL._theme_ui_category = _theme_creator_ui_category

BRIDGE_VERSION = "0.9.3"
from ExternalThemeCreatorVersion import get_workbench_version
EXTERNAL_THEME_CREATOR_PACKAGE_VERSION = get_workbench_version()


def _shared_settings_path() -> Path:
    """Use the legacy launcher's existing application-data namespace and filename."""
    path = UIL._app_config_base_dir() / UIL.SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _shared_fallback_path() -> Path:
    path = UIL._app_config_base_dir() / "freecad_executable.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_shared_settings() -> UIL.AppSettings:
    path = _shared_settings_path()
    if path.exists():
        try:
            return UIL._load_app_settings_from_path(path)
        except Exception:
            pass
    return UIL.AppSettings()


def _load_raw_settings() -> dict:
    path=_shared_settings_path()
    if path.exists():
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data,dict): return data
        except Exception:
            pass
    return {}



def _valid_cfg_filename_value(value: str) -> bool:
    value=str(value or "").strip()
    return bool(value and Path(value).name == value and Path(value).suffix.lower() == ".cfg")

def _resolve_creator_cfg_filename(theme_folder: Path, preferred: str = "") -> str:
    """Resolve the authoritative Creator CFG filename without blocking on stale settings.

    Priority:
      1. The one existing top-level .cfg (persistent development profile)
      2. theme-configuration.json output.filename (first initialization)
      3. saved preferred filename, if no configuration has specified a name

    A saved filename may belong to a different Theme Folder. Never let such a
    value override the existing development profile or configuration metadata.
    """
    cfgs=_top_level(theme_folder,'.cfg')
    if len(cfgs)==1:
        return cfgs[0].name
    # Multiple top-level CFGs are rejected by the caller; never select one
    # from stale settings in that situation.
    if len(cfgs)>1:
        return ""
    theme_config_path=theme_folder / UIL.THEME_CONFIGURATION_FILENAME
    if theme_config_path.is_file():
        try:
            data=json.loads(theme_config_path.read_text(encoding="utf-8"))
            candidate=str(((data.get("output") or {}).get("filename") or "")).strip()
            if _valid_cfg_filename_value(candidate):
                return candidate
        except Exception:
            pass
    preferred=str(preferred or "").strip()
    return preferred if _valid_cfg_filename_value(preferred) else ""

def _creator_options(force_all=False) -> dict:
    raw=_load_raw_settings()
    if force_all:
        return {
            "use_external_theme_stylesheet_assets": True,
            "use_external_configuration": True,
            "use_external_ui_scripts": True,
        }
    return {
        "use_external_theme_stylesheet_assets": bool(raw.get("use_external_theme_stylesheet_assets",True)),
        "use_external_configuration": bool(raw.get("use_external_configuration",True)),
        "use_external_ui_scripts": bool(raw.get("use_external_ui_scripts",True)),
    }

def _preserve_creator_options(options: dict) -> None:
    path=_shared_settings_path()
    try:
        data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception:
        data={}
    if not isinstance(data,dict): data={}
    data.update({
        'use_external_theme_stylesheet_assets':bool(options.get('use_external_theme_stylesheet_assets',True)),
        'use_external_configuration':bool(options.get('use_external_configuration',True)),
        'use_external_ui_scripts':bool(options.get('use_external_ui_scripts',True)),
    })
    path.write_text(json.dumps(data,indent=2),encoding='utf-8')

def _configure_packaged_theme_runtime_location() -> None:
    """Route packaged-theme extraction/runtime through the user-selected base folder.

    This deliberately does not move the shared launcher settings/state tree. It only
    changes the temporary extracted runtime used for a .fctheme launch.
    """
    raw=_load_raw_settings()
    value=str(raw.get('theme_runtime_location','') or '').strip()
    if not value:
        return
    base=Path(value).expanduser().resolve()
    base.mkdir(parents=True,exist_ok=True)
    def _make_runtime_dir():
        import secrets
        path=base / ('.uix_'+secrets.token_hex(8))
        path.mkdir(parents=True,exist_ok=False)
        return path
    def _is_safe_runtime_dir(path):
        if path is None:return False
        try:
            resolved=Path(path).resolve(); root=base.resolve()
        except Exception:return False
        if not resolved.exists() or not resolved.is_dir() or resolved==root:return False
        try:resolved.relative_to(root)
        except ValueError:return False
        return resolved.name.startswith('.uix_')
    UIL._make_obscured_temp_dir=_make_runtime_dir
    UIL._is_safe_temporary_cleanup_dir=_is_safe_runtime_dir

def _use_persistent_appimage(app):
    image = str(os.environ.get('APPIMAGE', '') or '').strip()
    if platform.system().lower() == 'linux' and image and Path(image).is_file():
        app.settings.freecad_executable = image
        if 'freecad_executable' in app.vars:
            app.vars['freecad_executable'].set(image)


def _prepare_app() -> UIL.ThemeLauncherApp:
    """Create the bundled launcher app, hidden, against the shared settings file."""
    app = UIL.ThemeLauncherApp()
    app.withdraw()
    app.settings_path = _shared_settings_path()
    app.freecad_executable_fallback_path = _shared_fallback_path()
    app.settings = _load_shared_settings()
    app._populate_ui_from_settings()
    _use_persistent_appimage(app)
    return app


# Retain the actual error from headless launches so Finder-created shortcuts
# can report it to the user rather than disappearing without explanation.
_LAST_HEADLESS_ERROR = ''


def _show_headless_error(message: str) -> None:
    global _LAST_HEADLESS_ERROR
    _LAST_HEADLESS_ERROR = str(message)
    print(_LAST_HEADLESS_ERROR, file=sys.stderr)


def _report_macos_creator_shortcut_error(message: str) -> None:
    """Write an actionable diagnostic and show a Finder-friendly error dialog.

    Do not write any data into the developer's Theme Folder or FreeCAD's cfg.
    """
    from datetime import datetime
    message = str(message or 'Unknown Develop Theme shortcut error')
    store = UIL._app_config_base_dir() / 'MacShortcuts'
    try:
        store.mkdir(parents=True, exist_ok=True)
        with (store / 'develop-shortcut-error.log').open('a', encoding='utf-8') as out:
            out.write(datetime.now().isoformat(timespec='seconds') + ' ' + message + '\n')
    except OSError:
        pass
    if platform.system().lower() != 'darwin':
        return
    # AppleScript arguments are passed as distinct argv elements (no shell or
    # source-code interpolation), so unusual theme paths are safe to display.
    try:
        subprocess.run([
            '/usr/bin/osascript',
            '-e', 'on run argv',
            '-e', 'display alert "External Theme Creator" message (item 1 of argv) as critical buttons {"OK"}',
            '-e', 'end run',
            message[:1800],
        ], capture_output=True, text=True, timeout=30)
    except Exception:
        pass


def _shortcut_splash_log(runtime_root: Path, message: str) -> None:
    """Persist failures only; routine launches should not accumulate logs."""
    if not any(token in message.upper() for token in ('ERROR', 'FALLBACK', 'FAILED')):
        return
    from datetime import datetime
    paths = [runtime_root / 'splash-startup.log']
    if os.name == 'nt':
        paths.append(Path(os.environ.get('APPDATA') or str(Path.home())) / 'External Theme Creator' / 'shortcut-splash.log')
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as output:
                output.write(datetime.now().isoformat(timespec='seconds') + ' SHORTCUT ' + message + '\n')
        except OSError:
            pass


def _wait_for_creator_main_window(process, timeout: float = 100.0) -> bool:
    """Wait until the launched FreeCAD process owns a visible main window."""
    if os.name != 'nt':
        start = time.monotonic()
        while time.monotonic() - start < min(timeout, 5.0):
            if process.poll() is not None:
                return False
            time.sleep(0.2)
        return True
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def has_window(pid):
        found = [False]
        @callback_type
        def visit(hwnd, _):
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if process_id.value == pid and user32.IsWindowVisible(hwnd):
                rect = wintypes.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)) and rect.right - rect.left > 400 and rect.bottom - rect.top > 250:
                    found[0] = True
                    return False
            return True
        user32.EnumWindows(visit, 0)
        return found[0]
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if process.poll() is not None:
            return False
        if has_window(process.pid):
            return True
        time.sleep(0.2)
    return False


def _prepare_user_launch_for_appimage(theme_file: str = "") -> int:
    """Prepare a packaged theme now, letting a persistent helper start it later.

    The runtime runs in the current AppImage's bundled Python before unmount.
    It does not launch an intermediate FreeCAD GUI.
    """
    import types
    app = None
    try:
        _configure_packaged_theme_runtime_location()
        app = _prepare_app()
        theme = str(theme_file or app.settings.theme_file or '').strip()
        if not theme or not Path(theme).is_file():
            raise UIL.LauncherError('Selected .fctheme file was not found: ' + theme)
        image = str(os.environ.get('APPIMAGE') or '').strip()
        if not image or not Path(image).is_file():
            raise UIL.LauncherError('A persistent APPIMAGE path is required for direct restart.')
        app.vars['user_mode'].set(True)
        app.vars['creator_mode'].set(False)
        selected_theme = str(Path(theme).resolve())
        app.vars['theme_file'].set(selected_theme)
        app.settings.theme_file = selected_theme
        # The bundled launcher's Tk settings collection can overwrite an explicitly
        # selected theme with a blank hidden entry during shortcut preparation.
        # Keep the caller's validated selection authoritative in this one operation.
        original_collect = app._collect_ui_to_settings
        def collect_with_selected_theme():
            original_collect()
            app.settings.theme_file = selected_theme
            app.vars['theme_file'].set(selected_theme)
        app._collect_ui_to_settings = collect_with_selected_theme
        captured = {}
        def prepare_only(self, **kwargs):
            # Reuse the launcher package verification/extraction and startup
            # command builder, but do not start FreeCAD from this process.
            self.save_settings()
            command, environment, summary, runtime_cfg = self._build_launch_command_for_theme_folder(
                theme_folder=kwargs['theme_folder'].resolve(),
                cfg_source=kwargs['cfg_source'].resolve(),
                cfg_writeback_target=kwargs['cfg_writeback_target'].resolve(),
                source_label=kwargs['source_label'],
                splash_override_path=kwargs.get('splash_override_path'),
                qss_override_path=kwargs.get('qss_override_path'),
                resolved_freecad_executable=kwargs.get('resolved_freecad_executable'),
                raw_freecad_executable_text=kwargs.get('raw_freecad_executable_text', ''),
            )
            cfg = kwargs['cfg_source'].resolve()
            home = cfg.parent / 'user_home'
            home.mkdir(parents=True, exist_ok=True)
            self._connect_user_workbenches(home)
            environment['FREECAD_USER_HOME'] = str(home)
            command[0] = str(Path(image).resolve())
            # Remove inherited AppImage mount state. The new mount supplies its own.
            for key in ('APPDIR', 'ARGV0', 'OWD', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONHOME'):
                environment.pop(key, None)
            captured.update(cmd=command, env=environment, cwd=str(Path(image).parent))
        app._launch_with_prepared_theme = types.MethodType(prepare_only, app)
        app.launch_from_theme_clicked()
        if not captured:
            raise UIL.LauncherError('Packaged-theme preparation did not produce a launch command. Check theme validation and launcher logs.')
        print(json.dumps(captured, ensure_ascii=False))
        return 0
    except Exception as exc:
        _show_headless_error('AppImage theme preparation failed: ' + str(exc))
        return 1
    finally:
        if app is not None:
            try: app.destroy()
            except Exception: pass


def _launch(mode: str, force_all: bool=False, *, theme_override: str="", settings_override: Path | None=None, creator_folder_override: str="") -> int:
    app = None
    try:
        if mode == 'creator':
            raw=_load_raw_settings()
            # For an independently launched shortcut, prefer the folder that
            # was selected at creation time over mutable global ETC settings.
            folder=str(creator_folder_override or raw.get('theme_folder','') or '').strip()
            if not folder:
                settings=_load_shared_settings(); folder=str(settings.theme_folder or '').strip()
            if not folder:
                raise UIL.LauncherError("Saved setting 'Theme Folder' is empty.")
            folder_path=Path(folder).expanduser().resolve()
            if not folder_path.is_dir():
                raise UIL.LauncherError('Develop Theme shortcut folder is unavailable: ' + str(folder_path))
            folder=str(folder_path)
            data=_prepare_creator_data(folder,force_all=force_all)
            cmd=[str(x) for x in data['cmd']]
            env={str(k):str(v) for k,v in data['env'].items()}
            runtime_root = Path(data['runtime_root'])
            theme_folder = Path(folder).expanduser().resolve()
            _shortcut_splash_log(runtime_root, 'Creator launch entered; folder=' + str(theme_folder))
            splash_source = theme_folder / 'splash' / 'freecadsplash.png'
            # Match the icon selection used by the working macOS shortcuts.
            # Keep a stable runtime copy so startup macros never depend on a
            # transient extraction or on a separate fallback lookup.
            creator_dock_icon = None
            if sys.platform == 'darwin':
                import shutil
                from ExternalThemeCreatorSplashControl import _macos_dock_icon_path
                source_icon = _macos_dock_icon_path(theme_folder)
                if source_icon is not None and Path(source_icon).is_file():
                    runtime_icon = runtime_root / 'creator_restart_dock_icon.icns'
                    if Path(source_icon).resolve() != runtime_icon.resolve():
                        shutil.copy2(source_icon, runtime_icon)
                    creator_dock_icon = runtime_icon
                _shortcut_splash_log(runtime_root, 'Creator restart Dock icon: ' + str(creator_dock_icon or 'not found'))
            splash_handle = None
            suppressed_cfg = None
            cfg_path = Path(data['active_cfg'])
            from ExternalThemeCreatorSplashControl import (_splash_preference_allows_custom,
                                                   _prepare_suppressed_splash_launch,
                                                   _restore_splash_preference_after_failed_launch)
            splash_allowed, splash_reason = _splash_preference_allows_custom(cfg_path)
            _shortcut_splash_log(runtime_root, 'Splash preference from CFG: ' + splash_reason)
            if splash_allowed and data['options']['use_external_theme_stylesheet_assets'] and splash_source.is_file():
                splash_handle = UIL._start_native_pixel_splash(Path(cmd[0]), splash_source, runtime_root)
                if splash_handle:
                    try:
                        cmd, suppressed_cfg = _prepare_suppressed_splash_launch(
                            cmd, cfg_path, runtime_root,
                            dock_icon_path=creator_dock_icon)
                    except Exception:
                        UIL._stop_native_pixel_splash(splash_handle)
                        raise
                    _shortcut_splash_log(runtime_root, 'MODE: Custom splash; native FreeCAD splash suppressed for this launch only')
                else:
                    _shortcut_splash_log(runtime_root, 'FALLBACK: custom helper did not start')
            else:
                _shortcut_splash_log(runtime_root, 'No custom splash requested; CFG preference=' + splash_reason)
            mac_ready = None
            if sys.platform == 'darwin':
                from ExternalThemeCreatorSplashControl import _macos_bundle_launch
                cmd, env, mac_ready = _macos_bundle_launch(
                    cmd, env, runtime_root, creator_dock_icon)
            kwargs={'cwd':str(Path(cmd[0]).parent),'env':env}
            if os.name=='nt':
                # Match the console-free Develop theme restart path.  Some
                # FreeCAD development executables request their own console,
                # which Windows Terminal hosts as the temporary "Develop"
                # window.  CREATE_NO_WINDOW did not suppress it in v0.9.66.
                # DETACHED_PROCESS prevents the subprocess from attaching to a
                # console; do not combine it with CREATE_NEW_CONSOLE or
                # CREATE_NO_WINDOW.  Keep all standard streams disconnected.
                kwargs['creationflags']=(getattr(subprocess,'DETACHED_PROCESS',0)
                                         |getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
                kwargs['stdin']=subprocess.DEVNULL
                kwargs['stdout']=subprocess.DEVNULL
                kwargs['stderr']=subprocess.DEVNULL
            else: kwargs['start_new_session']=True
            try:
                process = subprocess.Popen(cmd, **kwargs)
            except Exception:
                UIL._stop_native_pixel_splash(splash_handle)
                _restore_splash_preference_after_failed_launch(suppressed_cfg)
                raise
            _shortcut_splash_log(runtime_root, 'FreeCAD launched pid=' + str(process.pid))
            if splash_handle:
                try:
                    if mac_ready is not None:
                        from ExternalThemeCreatorSplashControl import _wait_macos_gui_ready
                        ready = _wait_macos_gui_ready(process, mac_ready)
                    else:
                        ready = _wait_for_creator_main_window(process)
                    _shortcut_splash_log(runtime_root, 'FreeCAD main window detected=' + str(ready))
                except Exception as exc:
                    _shortcut_splash_log(runtime_root, 'Window detection error: ' + repr(exc))
                finally:
                    UIL._stop_native_pixel_splash(splash_handle)
                    _shortcut_splash_log(runtime_root, 'Custom splash stop requested')
            return 0

        if mode == 'user':
            _configure_packaged_theme_runtime_location()
        app = _prepare_app()
        if settings_override is not None:
            # A macOS shortcut has its own private settings file.  Do not rewrite
            # the source-theme selection or other preferences of normal ETC.
            app.settings_path = Path(settings_override)
        settings = app.settings
        exe = str(settings.freecad_executable or '').strip()
        if not exe:
            raise UIL.LauncherError("Saved setting 'FreeCAD executable' is empty.")
        app.vars['freecad_executable'].set(exe)
        if mode == 'user':
            theme = str(theme_override or settings.theme_file or '').strip()
            if not theme:
                raise UIL.LauncherError("Saved setting 'Theme' is empty.")
            p = Path(theme).expanduser()
            if not p.is_file():
                raise UIL.LauncherError(f'Saved Theme was not found:\n{p}')
            app.vars['user_mode'].set(True)
            app.vars['creator_mode'].set(False)
            app.vars['theme_file'].set(str(p.resolve()))
            # Explicit CLI path wins even if the hidden Tk settings form was stale.
            app.settings.theme_file = str(p.resolve())
            app._collect_ui_to_settings()
            app.launch_from_theme_clicked()
        else:
            raise UIL.LauncherError(f'Unsupported launch mode: {mode}')
        try:
            if int(app.winfo_exists()): app.destroy()
        except Exception: pass
        return 0
    except Exception as exc:
        if app is not None:
            try:
                if int(app.winfo_exists()): app.destroy()
            except Exception: pass
        _show_headless_error(str(exc))
        return 1


def _top_level(folder: Path, suffix: str):
    return sorted((x for x in folder.iterdir() if x.is_file() and x.suffix.lower()==suffix), key=lambda x:x.name.lower())


def _write_theme_scripts_startup(runtime_root: Path, theme_folder: Path, qss_macro: Path | None=None) -> Path:
    macro=runtime_root/'apply_theme_creator_startup.FCMacro'
    module_dir=Path(__file__).resolve().parent
    lines=[
        'from __future__ import annotations',
        'import sys',
        'try:',
        '    from PySide import QtCore',
        'except Exception:',
        '    from PySide6 import QtCore',
        'import FreeCADGui as Gui',
        'MODULE_DIR='+repr(str(module_dir)),
        'THEME_FOLDER='+repr(str(theme_folder.resolve())),
        'QSS_MACRO='+repr(str(qss_macro.resolve()) if qss_macro is not None else ''),
        'if MODULE_DIR not in sys.path: sys.path.insert(0,MODULE_DIR)',
        'if QSS_MACRO:',
        '    try:',
        "        exec(compile(open(QSS_MACRO, 'r', encoding='utf-8').read(), QSS_MACRO, 'exec'), globals(), globals())",
        '    except Exception as exc:',
        '        try:',
        '            import FreeCAD as App',
        "            App.Console.PrintError('External Theme Creator: startup QSS macro failed: '+str(exc)+'\\n')",
        '        except Exception:',
        '            pass',
        'def _load_theme_scripts():',
        '    try:',
        '        if Gui.getMainWindow() is None:',
        '            QtCore.QTimer.singleShot(250,_load_theme_scripts); return',
        '        import ThemeScriptManager as TSM',
        '        TSM.install_from_folder(THEME_FOLDER)',
        '    except Exception as exc:',
        '        try:',
        '            import FreeCAD as App',
        "            App.Console.PrintError('External Theme Creator: theme script startup failed: '+str(exc)+'\\n')",
        '        except Exception:',
        '            pass',
        'QtCore.QTimer.singleShot(500,_load_theme_scripts)',
    ]
    macro.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return macro


def _prepare_creator_data(folder: str, force_all: bool=False) -> dict:
    app=None
    try:
        app=_prepare_app()
        p=Path(folder).expanduser().resolve()
        if not p.is_dir():
            raise UIL.LauncherError(f'Theme Folder was not found:\n{p}')

        options=_creator_options(force_all)
        app.vars['user_mode'].set(False)
        app.vars['creator_mode'].set(True)
        app.vars['theme_folder'].set(str(p))
        app._collect_ui_to_settings()
        app._persist_critical_paths()
        # Apply the four independent Develop-theme switches to the actual
        # Launcher builder, not merely to post-processing of its command.
        app.settings.use_external_theme_stylesheet_assets = options['use_external_theme_stylesheet_assets']
        app.settings.use_external_configuration = options['use_external_configuration']
        app.settings.use_external_ui_scripts = options['use_external_ui_scripts']
        # Icons can be provided via the environment alone. An isolated user
        # home is necessary for configurations/QSS/scripts, not icons alone.
        app.settings.use_freecad_user_home = True
        # The bundled launcher can load icon preferences from its saved settings.
        # Preserve them, except when preparing a complete packaged theme.
        app.settings.close_after_freecad_launch=True
        if force_all:
            app.settings.enable_external_icon_theme=True
            app.settings.prefer_external_icons=True

        resolved_exe,raw_exe_text=app._require_freecad_executable_now()
        scan_cfg,scan_qss,splash_path,icon_theme_root,notes=app._scan_specific_theme_folder(p)

        qss_files=_top_level(p,'.qss')
        qss_path=None
        if options['use_external_theme_stylesheet_assets']:
            if len(qss_files)!=1:
                raise UIL.LauncherError(f'Theme Folder must contain exactly one top-level .qss file when external stylesheet/assets are enabled; found {len(qss_files)}.')
            qss_path=qss_files[0].resolve()

        # The Theme Folder owns exactly one canonical development .cfg.
        # It is separate from normal FreeCAD and any applied .fctheme profile.
        # FreeCAD reads and writes this file directly: no second CFG copy in
        # development_profile/, and no writeback to normal FreeCAD.
        source_user_cfg=None
        from ExternalThemeCreatorMigration import theme_runtime
        runtime_root=theme_runtime(p)
        runtime_root.mkdir(parents=True,exist_ok=True)
        cfg_files=_top_level(p,'.cfg')
        if len(cfg_files)>1:
            raise UIL.LauncherError('Theme Folder must contain exactly one top-level .cfg file at most; found '+str(len(cfg_files))+'.')
        cfg_initialized=False
        if cfg_files:
            active_cfg=cfg_files[0].resolve()
        else:
            desired=_resolve_creator_cfg_filename(p,str(getattr(app.settings,'creator_cfg_filename','') or ''))
            if not desired:
                desired='Theme.cfg'
            active_cfg=(p/desired).resolve()
            if active_cfg.exists():
                raise UIL.LauncherError('Cannot initialize development CFG: path already exists: '+str(active_cfg))
            source_user_cfg=app._resolve_creator_source_user_cfg(resolved_exe)
            if options['use_external_configuration'] and (p/UIL.THEME_CONFIGURATION_FILENAME).is_file():
                theme_config=UIL._load_theme_configuration(p/UIL.THEME_CONFIGURATION_FILENAME)
                UIL._apply_theme_configuration(source_user_cfg,active_cfg,theme_config)
            else:
                import shutil
                shutil.copy2(source_user_cfg,active_cfg)
            cfg_initialized=True
        # Disabling external configuration skips imports/layout operations;
        # it never redirects FreeCAD to its normal user.cfg.
        app.save_settings()
        # The actual persistent Theme Folder CFG is authoritative. Synchronize
        # the saved name so later validation and the CFG tools use this file.
        app.settings.creator_cfg_filename=active_cfg.name
        app._write_settings_file()
        _preserve_creator_options(options)
        cmd,env,summary,runtime_user_cfg=app._build_launch_command_for_theme_folder(
            theme_folder=p,
            cfg_source=active_cfg,
            cfg_writeback_target=active_cfg,
            source_label='Independent development profile',
            resolved_freecad_executable=resolved_exe,
            raw_freecad_executable_text=raw_exe_text,
        )
        from ExternalThemeCreatorMigration import theme_runtime
        runtime_root=theme_runtime(p)

        if not options['use_external_theme_stylesheet_assets']:
            cmd=[x for x in cmd if Path(str(x)).name!='apply_runtime_stylesheet.FCMacro']
        elif qss_path is not None:
            env['EXTERNAL_THEME_CREATOR_QSS_PATH']=str(qss_path)

        # Semantic layout instructions are part of external theme configuration.
        # If external configuration is disabled, do not apply them either.
        if not options['use_external_configuration']:
            cmd=[x for x in cmd if Path(str(x)).name!='apply_runtime_ui_layout.FCMacro']

        # Developer sessions need the same installed Addon workbenches as normal
        # FreeCAD.  The engine already has a link-only, no-copy implementation.
        development_home=(runtime_root/'development_user_home').resolve()
        development_home.mkdir(parents=True,exist_ok=True)
        app._connect_user_workbenches(development_home)
        env['FREECAD_USER_HOME']=str(development_home)
        if platform.system().lower()=='linux' and os.environ.get('APPIMAGE'):
            # These paths refer to the *old* AppImage mount. The permanent
            # .AppImage will establish its own runtime paths after restart.
            for key in ('APPDIR','ARGV0','OWD','LD_LIBRARY_PATH','LD_PRELOAD','PYTHONHOME','PYTHONPATH'):
                env.pop(key,None)
            image=Path(os.environ['APPIMAGE']).expanduser().resolve()
            if not image.is_file():
                raise UIL.LauncherError('Persistent APPIMAGE executable not found: '+str(image))
            cmd[0]=str(image)
        env['EXTERNAL_THEME_CREATOR_THEME_FOLDER']=str(p)
        env['EXTERNAL_THEME_CREATOR_UI_SCRIPTS_ENABLED']='1' if options['use_external_ui_scripts'] else '0'
        env['EXTERNAL_THEME_CREATOR_EXTERNAL_QSS_ENABLED']='1' if options['use_external_theme_stylesheet_assets'] else '0'
        env['EXTERNAL_THEME_CREATOR_EXTERNAL_CFG_ENABLED']='1' if options['use_external_configuration'] else '0'

        scripts_dir=p/'scripts'
        scripts_macro=None
        if options['use_external_ui_scripts']:
            qss_macro=runtime_root/'apply_runtime_stylesheet.FCMacro'
            use_qss_macro=qss_macro if options['use_external_theme_stylesheet_assets'] and qss_macro.is_file() else None
            # Use one startup macro so QSS setup and script installation have a
            # deterministic order. The original generated QSS macro is executed
            # from this wrapper, then scripts are installed after the GUI exists.
            cmd=[x for x in cmd if Path(str(x)).name!='apply_runtime_stylesheet.FCMacro']
            scripts_macro=_write_theme_scripts_startup(runtime_root,p,use_qss_macro)
            cmd.append(str(scripts_macro))

        result={
            'cmd':list(cmd),'env':dict(env),'summary':str(summary),'runtime_root':str(runtime_root),
            'active_cfg':str(active_cfg),'theme_folder_cfg':str(next(iter(_top_level(p,'.cfg')),'')) if options['use_external_configuration'] else '',
            'source_user_cfg':str(source_user_cfg) if source_user_cfg is not None else '',
            'cfg_initialized':cfg_initialized,
            'qss':str(qss_path) if qss_path else '',
            'qss_assets':str(p/'qss-assets'),
            'scripts':str(scripts_dir),
            'scripts_macro':str(scripts_macro) if scripts_macro else '',
            'options':options,
        }
        return result
    finally:
        if app is not None:
            try:app.destroy()
            except Exception:pass


def _prepare_creator(folder: str) -> int:
    try:
        print(json.dumps(_prepare_creator_data(folder),ensure_ascii=False))
        return 0
    except Exception as exc:
        _show_headless_error(str(exc));return 1


def _validate_creator(folder: str) -> int:
    try:
        p=Path(folder).expanduser().resolve()
        if not p.is_dir(): raise UIL.LauncherError(f'Theme Folder was not found:\n{p}')
        options=_creator_options(False)
        raw=_load_raw_settings()
        errors=[];warnings=[]
        qss_files=_top_level(p,'.qss')
        qss=''
        if options['use_external_theme_stylesheet_assets']:
            if len(qss_files)!=1: errors.append(f'External stylesheet/assets are enabled, but Theme Folder contains {len(qss_files)} top-level .qss files; exactly one is required.')
            elif qss_files: qss=str(qss_files[0].resolve())
            if not (p/'qss-assets').is_dir(): warnings.append('Standard qss-assets folder is not present. This is allowed if the stylesheet does not need external QSS assets.')
        cfg=''
        cfg_files=_top_level(p,'.cfg')
        # The existing profile is authoritative, but semantic layout actions
        # still come from JSON. Report malformed JSON instead of quietly
        # dropping the user's intended layout on the next restart.
        instructions=p/UIL.THEME_CONFIGURATION_FILENAME
        if options['use_external_configuration'] and instructions.is_file():
            try:
                UIL._load_theme_configuration(instructions)
            except Exception as exc:
                errors.append('Invalid theme-configuration.json: '+str(exc))
        if len(cfg_files)>1:
            errors.append('Theme Folder contains multiple top-level .cfg files: '+', '.join(x.name for x in cfg_files)+'. Keep only the intended development profile at the top level.')
        elif options['use_external_configuration']:
            desired=_resolve_creator_cfg_filename(p,str(raw.get('creator_cfg_filename','') or ''))
            if not desired:
                errors.append('Cannot determine development .cfg filename from the Theme Folder or theme-configuration.json.')
            else:
                expected=(p/desired).resolve(); cfg=str(expected)
                if not expected.is_file() and not (p/UIL.THEME_CONFIGURATION_FILENAME).is_file():
                    errors.append('Development .cfg does not exist and theme-configuration.json is unavailable to initialize it.')
        scripts_dir=p/'scripts'
        if options['use_external_ui_scripts'] and not scripts_dir.is_dir():
            warnings.append('External UI scripts are enabled, but the optional scripts folder is not present.')
        # Reuse Launcher's scan for splash and icon-root reporting only.
        app=_prepare_app()
        try:
            app.vars['theme_folder'].set(str(p));app._collect_ui_to_settings()
            _cfg,_qss,splash,icon_root,notes=app._scan_specific_theme_folder(p)
        finally:
            try:app.destroy()
            except Exception:pass
        result={'ok':not errors,'errors':errors,'warnings':warnings,'cfg':cfg,'qss':qss,
                'splash':str(splash) if splash else '','icon_root':str(icon_root) if icon_root else '',
                'qss_assets':str(p/'qss-assets'),'scripts':str(scripts_dir),'options':options}
        print(json.dumps(result,ensure_ascii=False));return 0
    except Exception as exc:
        _show_headless_error(str(exc));return 1


def _export_request(request_path: str) -> int:
    app = None
    try:
        req = json.loads(Path(request_path).read_text(encoding="utf-8"))
        values = dict(req["values"]); values["theme_creator_version"] = EXTERNAL_THEME_CREATOR_PACKAGE_VERSION; output = Path(req["output_path"]).expanduser().resolve()
        app = _prepare_app()
        folder = Path(values["theme_folder"]).expanduser().resolve()
        app.vars["theme_folder"].set(str(folder)); app._collect_ui_to_settings()
        scan = app._scan_theme_folder_for_export()
        manifest, path = app._create_theme_package(values, scan, output)
        print(json.dumps({"output_path": str(path), "manifest": manifest}, ensure_ascii=False)); return 0
    except Exception as exc:
        _show_headless_error(str(exc)); return 1
    finally:
        if app is not None:
            try: app.destroy()
            except Exception: pass

def _create_direct_appimage_shortcut(shortcut_path: Path, source: str, mode: str) -> tuple[Path, list[str]]:
    """Save a prepared, persistent user or creator launch without a GUI bootstrap.

    Called under FreeCAD's bundled Python while the original AppImage is mounted.
    The resulting shortcut only needs a persistent system Python interpreter.
    """
    import contextlib
    import hashlib
    import io
    import shutil

    system_python = next((Path(p) for p in ('/usr/bin/python3', shutil.which('python3'))
                          if p and Path(p).is_file() and os.access(p, os.X_OK)
                          and '/.mount_' not in str(p)), None)
    if system_python is None:
        raise UIL.LauncherError('A persistent system Python 3 is needed for AppImage shortcuts.')

    if mode=='creator':
        prepared = _prepare_creator_data(source)
        prepared['cwd']=str(Path(prepared['cmd'][0]).parent)
    elif mode=='user':
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = _prepare_user_launch_for_appimage(source)
        if result != 0:
            raise UIL.LauncherError('Could not prepare the themed AppImage shortcut.')
        try:
            prepared=json.loads(output.getvalue().strip())
        except (TypeError,ValueError) as exc:
            raise UIL.LauncherError('Invalid user-theme launch preparation: '+str(exc)) from exc
    else:
        raise UIL.LauncherError('Unsupported AppImage shortcut mode: '+str(mode))
    try:
        cmd = prepared['cmd']
        env = prepared['env']
        cwd = prepared['cwd']
        if not isinstance(cmd, list) or not cmd or not isinstance(env, dict):
            raise ValueError('Unexpected command/environment shape')
        if not Path(cmd[0]).is_file():
            raise ValueError('AppImage executable no longer exists')
    except (KeyError, TypeError, ValueError) as exc:
        raise UIL.LauncherError('Invalid AppImage launch preparation: ' + str(exc)) from exc

    # Keep per-shortcut settings stable; names may be reused in different folders.
    from ExternalThemeCreatorMigration import application_dir
    key = hashlib.sha256(str(shortcut_path.resolve()).encode('utf-8')).hexdigest()[:20]
    store = application_dir() / 'AppImageShortcuts'
    store.mkdir(parents=True, exist_ok=True)
    spec_path = store / ('shortcut_' + key + '.json')
    runner_path = store / 'launch_prepared_appimage.py'
    runner_source = """#!/usr/bin/env python3
'''Launch a pre-prepared ETC AppImage theme without opening bootstrap FreeCAD.'''
import json
import os
from pathlib import Path
import subprocess
import sys

def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    cmd = spec['cmd']
    env = spec['env']
    cwd = spec['cwd']
    # Avoid leaking launcher-specific AppImage mount settings from the caller.
    for key in ('APPDIR', 'ARGV0', 'OWD', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONHOME'):
        env.pop(key, None)
    subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logfile = Path(__file__).with_name('shortcut-error.log')
        with logfile.open('a', encoding='utf-8') as stream:
            stream.write(str(exc) + '\\n')
        raise
"""
    runner_path.write_text(runner_source, encoding='utf-8')
    spec_path.write_text(json.dumps({'cmd': cmd, 'env': env, 'cwd': cwd}, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        spec_path.chmod(0o600)
    except OSError:
        pass
    return system_python, [str(runner_path), str(spec_path)]



def _stage_macos_shortcut_theme(source: Path, shortcut_path: Path) -> Path:
    """Store a private theme snapshot outside macOS Desktop/Documents protections.

    FreeCAD can read the selected package in its own process, but a generated
    .app shortcut has a different macOS privacy identity and may get EPERM when
    reopening the original package from Desktop/Documents/Downloads.

    Each shortcut gets a stable, per-shortcut copy in Application Support.
    Recreating a shortcut updates that copy atomically, without altering the
    selected source or shared ETC settings.
    """
    import hashlib
    import shutil
    import tempfile
    if not source.is_file() or source.suffix.lower() != '.fctheme':
        raise UIL.LauncherError('Select an existing .fctheme file before creating a shortcut.')
    store_id = hashlib.sha256(str(shortcut_path.absolute()).encode('utf-8')).hexdigest()[:20]
    store = UIL._app_config_base_dir() / 'MacShortcuts' / store_id
    store.mkdir(parents=True, exist_ok=True)
    destination = store / 'theme.fctheme'
    fd, temporary_name = tempfile.mkstemp(prefix='.theme-', suffix='.tmp', dir=store)
    try:
        with os.fdopen(fd, 'wb') as out, source.open('rb') as original:
            shutil.copyfileobj(original, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary_name, destination)
        destination.chmod(0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return destination


def _macos_freecad_bundle(executable: str) -> Path:
    """Locate the installed .app for Launch Services, not the helper Python.

    Launch Services gives the new GUI process the FreeCAD application's own
    privacy identity; a Finder-launched Python wrapper doesn't have FreeCAD's
    existing access to Desktop/Documents development folders.
    """
    raw = Path(executable).expanduser()
    for candidate in (raw, *raw.parents):
        if candidate.suffix.lower() == '.app' and candidate.is_dir():
            return candidate.absolute()
    # Some FreeCAD executables are symlinks into a bundle.
    resolved = raw.resolve()
    for candidate in (resolved, *resolved.parents):
        if candidate.suffix.lower() == '.app' and candidate.is_dir():
            return candidate.absolute()
    raise UIL.LauncherError(
        'The macOS Develop Theme shortcut requires a FreeCAD.app bundle. '
        'Select FreeCAD.app in ETC Settings and create the shortcut again.'
    )


def _macos_direct_creator_shortcut(folder: Path, shortcut_path: Path, prepared_override: dict | None = None, dock_icon_path: Path | None = None) -> tuple[Path, list[str], dict | None]:
    """Prepare from the *authorized* FreeCAD session, then launch FreeCAD itself.

    No Finder-launched Python process opens or scans the protected Theme Folder.
    The original folder remains authoritative for CFG, icons and scripts.
    """
    prepared = prepared_override if prepared_override is not None else _prepare_creator_data(str(folder))
    command = [str(value) for value in prepared['cmd']]
    environment = {str(k): str(v) for k, v in prepared['env'].items()}
    if not command:
        raise UIL.LauncherError('Develop Theme preparation produced no FreeCAD command.')
    bundle = _macos_freecad_bundle(command[0])

    # open(1) --env supplies the themed environment to the new *application*
    # instance rather than a standalone Python process. Explicit empty icon
    # values prevent a previous profile from leaking into a disabled option.
    keys = (
        'FREECAD_USER_HOME',
        'FREECAD_EXTERNAL_ICON_THEME',
        'FREECAD_EXTERNAL_ICON_THEME_ENABLED',
        'FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL',
        'EXTERNAL_THEME_CREATOR_QSS_PATH',
        'EXTERNAL_THEME_CREATOR_THEME_FOLDER',
        'EXTERNAL_THEME_CREATOR_UI_SCRIPTS_ENABLED',
        'EXTERNAL_THEME_CREATOR_EXTERNAL_QSS_ENABLED',
        'EXTERNAL_THEME_CREATOR_EXTERNAL_CFG_ENABLED',
    )
    arguments = ['-n', '-a', str(bundle)]
    for key in keys:
        arguments.extend(['--env', key + '=' + environment.get(key, '')])
    splash_spec = None
    # Restart with theme uses the native-pixel Qt splash helper and watches
    # FreeCAD's GUI before dismissing it. The old macOS .app shortcut ran
    # `open` directly, so only FreeCAD's differently sized native splash appeared.
    # Stage only the splash and readiness macro under Application Support: a
    # Finder-launched shortcut has no TCC permission to read the Desktop theme.
    splash_source = folder / 'splash' / 'freecadsplash.png'
    cfg = Path(prepared['active_cfg'])
    from ExternalThemeCreatorSplashControl import (
        _splash_preference_allows_custom, _find_freecad_python,
        _freecad_qt_platform_plugins,
    )
    splash_allowed, _reason = _splash_preference_allows_custom(cfg)
    if (splash_allowed and splash_source.is_file() and
            prepared['options']['use_external_theme_stylesheet_assets']):
        import hashlib
        import shutil
        storage_id = hashlib.sha256(str(shortcut_path.absolute()).encode('utf-8')).hexdigest()[:20]
        splash_dir = UIL._app_config_base_dir() / 'MacShortcuts' / storage_id
        splash_dir.mkdir(parents=True, exist_ok=True)
        staged_image = splash_dir / 'develop-splash.png'
        # A direct byte copy keeps the PNG's source resolution unchanged.
        shutil.copy2(splash_source, staged_image)
        py = _find_freecad_python(Path(command[0]))
        helper = Path(__file__).resolve().with_name('ExternalThemeCreatorStartupSplash.py')
        if py is None or not helper.is_file():
            raise UIL.LauncherError('FreeCAD splash Python or the ETC splash helper is missing.')
        ready_file = splash_dir / 'develop-gui-ready.flag'
        ready_macro = splash_dir / 'signal_develop_shortcut_ready.FCMacro'
        ready_macro.write_text("import FreeCADGui as Gui\nfrom pathlib import Path\ntry:\n    from PySide import QtCore\nexcept ImportError:\n    from PySide6 import QtCore\nREADY_FILE = Path({ready!r})\ndef _etc_ready():\n    mw = Gui.getMainWindow()\n    if mw is not None and mw.isVisible():\n        QtCore.QTimer.singleShot(900, lambda: READY_FILE.write_text('ready', encoding='ascii'))\n    else:\n        QtCore.QTimer.singleShot(250, _etc_ready)\nQtCore.QTimer.singleShot(750, _etc_ready)\n".format(ready=str(ready_file)), encoding='utf-8')
        from ExternalThemeCreatorSplashControl import _macos_dock_icon_code, _macos_dock_icon_path
        # The .app icon is copied to this permanent location by _create_macos_shortcut.
        # The original Apply Theme package icon may live in a temporary extraction.
        bundled_icon = shortcut_path / 'Contents' / 'Resources' / 'shortcut.icns'
        selected_icon = bundled_icon if dock_icon_path else _macos_dock_icon_path(folder)
        if selected_icon:
            ready_macro.write_text(ready_macro.read_text(encoding='utf-8') + '\n' +
                                   _macos_dock_icon_code(selected_icon, allow_future_file=True), encoding='utf-8')
        # macOS Finder shortcuts cannot modify a TCC-protected Desktop CFG.
        # --set-config does not reliably suppress FreeCAD's native splash.
        # Use a shortcut-owned CFG snapshot, initialized while ETC has access,
        # with ShowSplasher=0. This avoids modifying the LIVE development CFG.
        # Limitation: edits made in FreeCAD while launched via this shortcut
        # are saved to the shortcut CFG, not automatically to the live CFG.
        import shutil
        from ExternalThemeCreatorSplashControl import _set_theme_profile_splash_disabled
        shortcut_cfg = splash_dir / 'develop-shortcut-user.cfg'
        shutil.copy2(cfg, shortcut_cfg)
        _set_theme_profile_splash_disabled(shortcut_cfg, True)
        try:
            index = command.index('--user-cfg')
            if index + 1 >= len(command):
                raise ValueError('--user-cfg has no filename')
            command[index + 1] = str(shortcut_cfg)
        except ValueError as exc:
            raise UIL.LauncherError('Develop shortcut is missing a user CFG argument.') from exc
        command.append(str(ready_macro))
        platform_plugins = _freecad_qt_platform_plugins(Path(command[0]), py)
        splash_spec = {
            'python': str(py), 'helper': str(helper), 'image': str(staged_image),
            'ready': str(ready_file), 'directory': str(splash_dir),
            'plugin_directory': str(platform_plugins) if platform_plugins else '',
        }
    arguments.extend(['--args', *command[1:]])
    return Path('/usr/bin/open'), arguments, splash_spec


def _macos_direct_user_shortcut(theme_file: Path, shortcut_path: Path, dock_icon_path: Path | None = None) -> tuple[Path, list[str], dict | None]:
    """Prepare the licensed theme *inside FreeCAD*, then launch only FreeCAD.app.

    The Finder app never starts an unsupported standalone FreeCAD Python process.
    Keep extracted resources in this shortcut's private Application Support directory.
    """
    import hashlib
    import shutil
    storage_id = hashlib.sha256(str(shortcut_path.absolute()).encode('utf-8')).hexdigest()[:20]
    store = UIL._app_config_base_dir() / 'MacShortcuts' / storage_id
    store.mkdir(parents=True, exist_ok=True)
    package = _stage_macos_shortcut_theme(theme_file, shortcut_path)
    app = _prepare_app()
    previous_extract = UIL._make_obscured_temp_dir
    captured = {}
    try:
        # Reuse exactly the package signature/license/external-asset/config
        # preparation path used by Apply Theme -> Restart with theme.
        def persistent_extract():
            root = store / 'apply_extracted'
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True)
            return root
        UIL._make_obscured_temp_dir = persistent_extract
        def prepare_only(self, **kwargs):
            command, environment, _summary, _runtime_cfg = self._build_launch_command_for_theme_folder(
                theme_folder=kwargs['theme_folder'].resolve(),
                cfg_source=kwargs['cfg_source'].resolve(),
                cfg_writeback_target=kwargs['cfg_writeback_target'].resolve(),
                source_label=kwargs['source_label'],
                splash_override_path=kwargs.get('splash_override_path'),
                qss_override_path=kwargs.get('qss_override_path'),
                resolved_freecad_executable=kwargs.get('resolved_freecad_executable'),
                raw_freecad_executable_text=kwargs.get('raw_freecad_executable_text', ''),
            )
            cfg = kwargs['cfg_source'].resolve()
            home = cfg.parent / 'user_home'
            home.mkdir(parents=True, exist_ok=True)
            self._connect_user_workbenches(home)
            environment['FREECAD_USER_HOME'] = str(home)
            captured.update(cmd=command, env=environment, active_cfg=str(cfg),
                            options={'use_external_theme_stylesheet_assets': self.settings.use_external_theme_stylesheet_assets},
                            folder=str(kwargs['theme_folder'].resolve()))
        app._launch_with_prepared_theme = types.MethodType(prepare_only, app)
        app.vars['user_mode'].set(True)
        app.vars['creator_mode'].set(False)
        app.vars['theme_file'].set(str(package))
        app.settings.theme_file = str(package)
        # The selected path wins even if the hidden UI's state was stale.
        old_collect = app._collect_ui_to_settings
        def collect_selected():
            old_collect()
            app.settings.theme_file = str(package)
            app.vars['theme_file'].set(str(package))
        app._collect_ui_to_settings = collect_selected
        app.launch_from_theme_clicked()
        if not captured:
            raise UIL.LauncherError('Apply Theme preparation did not finish. Check the ETC package, license, and external resources.')
    finally:
        UIL._make_obscured_temp_dir = previous_extract
        try: app.destroy()
        except Exception: pass
    return _macos_direct_creator_shortcut(Path(captured['folder']), shortcut_path, captured, dock_icon_path=dock_icon_path)


def _create_shortcut(mode: str, name: str, location: str, force_all: bool=False, theme_source: str="") -> int:
    app=None;cleanup_dir=None
    try:
        app=_prepare_app()
        raw=_load_raw_settings()
        if mode=='creator':
            folder=str(theme_source or raw.get('theme_folder','') or app.settings.theme_folder or '').strip()
            if not folder: raise UIL.LauncherError("Saved setting 'Theme Folder' is empty.")
            source=Path(folder).expanduser().resolve()
            if not source.is_dir(): raise UIL.LauncherError(f'Theme Folder was not found:\n{source}')
            icon_path,cleanup_dir=app._resolve_shortcut_icon_for_source(source)
            target_path=Path(sys.executable).resolve()
            # Resolve the latest saved Develop-theme options each time the shortcut runs.
            shortcut_arguments=[str(Path(__file__).resolve()),'--launch-as-creator']
        else:
            theme=str(theme_source or raw.get('theme_file','') or app.settings.theme_file or '').strip()
            if not theme: raise UIL.LauncherError("Saved setting 'Theme' is empty.")
            source=Path(theme).expanduser().resolve()
            icon_path,cleanup_dir=app._resolve_shortcut_icon_for_source(source)
            # Use the SSL-safe External Theme Creator bridge, just like Apply theme restart.
            # ExternalThemeCreatorLauncher.py imports ssl directly and fails in FreeCAD 26.3.
            target_path=Path(sys.executable).resolve()
            shortcut_arguments=[str(Path(__file__).resolve()), '--launch-as-user']
        if platform.system().lower() == 'windows':
            # Windows .lnk targets must not invoke the console Python executable.
            gui_python = target_path.with_name('pythonw.exe')
            if gui_python.is_file():
                target_path = gui_python
        location_path=Path(location).expanduser().resolve()
        if not location_path.is_dir(): raise UIL.LauncherError('Shortcut Location does not exist or is not a folder.')
        safe_name=str(name or 'FreeCAD').strip() or 'FreeCAD'
        system=platform.system().lower()
        if system == 'linux' and os.environ.get('APPIMAGE'):
            image = Path(os.environ['APPIMAGE']).resolve()
            if not image.is_file():
                raise UIL.LauncherError('APPIMAGE does not point to an existing file: '+str(image))
            target_path, shortcut_arguments = _create_direct_appimage_shortcut(
                location_path / (safe_name + '.desktop'), str(source), mode)
        if system=='windows':
            shortcut_path=location_path/f'{safe_name}.lnk';app._create_windows_shortcut(shortcut_path,target_path,shortcut_arguments,icon_path)
        elif system=='darwin':
            shortcut_path=location_path/f'{safe_name}.app'
            if mode == 'user':
                # Finder-launched .app shortcuts can be blocked by macOS TCC
                # from reading the original .fctheme under Desktop/Documents.
                # The source is accessible *now*, while ETC creates the shortcut.
                target_path, shortcut_arguments, macos_splash_spec = _macos_direct_user_shortcut(source, shortcut_path, dock_icon_path=icon_path)
            else:
                # Prepare while called from FreeCAD, which already has access to
                # the selected developer folder. The generated .app must not open
                # Desktop/Documents using its own unrelated Python/TCC identity.
                target_path, shortcut_arguments, macos_splash_spec = _macos_direct_creator_shortcut(source, shortcut_path, dock_icon_path=icon_path)
            app._create_macos_shortcut(shortcut_path,target_path,shortcut_arguments,icon_path,
                                       macos_splash_spec=macos_splash_spec)
        else:
            shortcut_path=location_path/f'{safe_name}.desktop';app._create_linux_shortcut(shortcut_path,target_path,shortcut_arguments,icon_path)
        print(str(shortcut_path));return 0
    except Exception as exc:
        _show_headless_error(str(exc));return 1
    finally:
        if cleanup_dir is not None:
            try:
                import shutil;shutil.rmtree(cleanup_dir,ignore_errors=True)
            except Exception:pass
        if app is not None:
            try:app.destroy()
            except Exception:pass



def _generate_cfg(old_cfg: str, new_cfg: str, filename: str, output_dir: str) -> int:
    """Headless CFG diff generation used by the modeless capture/comparison UI."""
    old_path=Path(old_cfg).expanduser().resolve()
    new_path=Path(new_cfg).expanduser().resolve()
    outdir=Path(output_dir).expanduser().resolve()
    if not old_path.is_file():
        raise UIL.LauncherError("Old CFG was not found: "+str(old_path))
    if not new_path.is_file():
        raise UIL.LauncherError("New CFG was not found: "+str(new_path))
    if not _valid_cfg_filename_value(filename):
        raise UIL.LauncherError("Generated CFG filename must be a filename ending in .cfg.")
    outdir.mkdir(parents=True,exist_ok=True)
    configuration, skipped = UIL._generate_theme_configuration(old_path,new_path,str(filename))
    config_path=outdir/UIL.THEME_CONFIGURATION_FILENAME
    skipped_path=outdir/UIL.THEME_CONFIGURATION_SKIPPED_FILENAME
    config_path.write_text(json.dumps(configuration,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    skipped_path.write_text(json.dumps(skipped,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"configuration":configuration,"skipped":skipped},ensure_ascii=False))
    return 0

def _wait_for_pid_exit(pid: int) -> None:
    pid = int(pid)
    if pid <= 0:
        return
    if platform.system().lower() == "windows":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
            if handle:
                try:
                    ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
                return
        except Exception:
            pass
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.25)


def main() -> int:
    args = sys.argv[1:]
    try:
        if "--wait-for-pid" in args:
            i = args.index("--wait-for-pid")
            if len(args) <= i + 1:
                raise UIL.LauncherError("A PID is required after --wait-for-pid.")
            _wait_for_pid_exit(int(args[i + 1]))
        if "--prepare-creator" in args:
            i = args.index("--prepare-creator")
            if len(args) <= i + 1:
                raise UIL.LauncherError("--prepare-creator requires a Theme Folder")
            return _prepare_creator(args[i + 1])
        if "--prepare-user-appimage" in args:
            return _prepare_user_launch_for_appimage()
        if "--launch-macos-creator-shortcut" in args:
            i = args.index("--launch-macos-creator-shortcut")
            if len(args) <= i + 1:
                raise UIL.LauncherError("--launch-macos-creator-shortcut requires a Theme Folder")
            selected_folder = str(Path(args[i + 1]).expanduser().resolve())
            code = _launch('creator', creator_folder_override=selected_folder)
            if code:
                message = _LAST_HEADLESS_ERROR or 'Failed to start Develop Theme.'
                if 'Operation not permitted' in message or 'Permission denied' in message:
                    message += ('\n\nmacOS may be blocking this shortcut from opening the '
                                'Theme Folder. If the folder is under Desktop/Documents, '
                                'grant the shortcut permission or place the development '
                                'folder in an accessible location and recreate the shortcut.')
                _report_macos_creator_shortcut_error(message)
            return code
        if "--launch-macos-shortcut" in args:
            i = args.index("--launch-macos-shortcut")
            if len(args) <= i + 1:
                raise UIL.LauncherError("--launch-macos-shortcut requires a staged .fctheme path")
            selected = Path(args[i + 1]).expanduser().resolve()
            if selected.suffix.lower() != '.fctheme' or not selected.is_file():
                raise UIL.LauncherError('Shortcut theme file is missing. Recreate this shortcut from ETC: ' + str(selected))
            return _launch('user', theme_override=str(selected),
                           settings_override=selected.parent / 'settings.json')
        if "--launch-as-user" in args:
            return _launch("user")
        if "--launch-as-creator-all" in args:
            # Backwards compatibility with shortcuts made by v0.9.16:
            # never force assets; use current saved Develop-theme settings.
            return _launch("creator")
        if "--launch-as-creator" in args:
            return _launch("creator")
        if "--create-shortcut-user" in args or "--create-shortcut-creator" in args:
            flag = "--create-shortcut-user" if "--create-shortcut-user" in args else "--create-shortcut-creator"
            mode = "user" if flag.endswith("user") else "creator"
            i = args.index(flag)
            if len(args) <= i + 2:
                raise UIL.LauncherError("Shortcut name and location are required.")
            force_all='--all-assets' in args
            # The GUI supplies its currently selected package as an explicit path.
            # Do not depend on asynchronously saved launcher settings.
            theme_source = args[i + 3] if len(args) > i + 3 and not str(args[i+3]).startswith('--') else ''
            return _create_shortcut(mode, args[i + 1], args[i + 2], force_all=force_all, theme_source=theme_source)
        if "--generate-cfg" in args:
            i = args.index("--generate-cfg")
            if len(args) <= i + 4: raise UIL.LauncherError("--generate-cfg requires old.cfg new.cfg filename output_dir")
            return _generate_cfg(args[i+1], args[i+2], args[i+3], args[i+4])
        if "--validate-creator" in args:
            i = args.index("--validate-creator")
            if len(args) <= i + 1: raise UIL.LauncherError("--validate-creator requires a Theme Folder")
            return _validate_creator(args[i+1])
        if "--export-request" in args:
            i = args.index("--export-request")
            if len(args) <= i + 1: raise UIL.LauncherError("--export-request requires a JSON request file")
            return _export_request(args[i+1])
        if "--diagnostics-creator" in args:
            return _diagnostics()
        raise UIL.LauncherError("ExternalThemeCreatorRuntime.py is a headless bridge and requires an action argument.")
    except Exception as exc:
        _show_headless_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
