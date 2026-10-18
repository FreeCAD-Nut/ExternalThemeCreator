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
      1. valid configured filename
      2. theme-configuration.json output.filename
      3. exactly one top-level .cfg

    A differently named top-level CFG is still treated as an ambiguity once a
    filename has been resolved.
    """
    preferred=str(preferred or "").strip()
    if _valid_cfg_filename_value(preferred):
        return preferred
    theme_config_path=theme_folder / UIL.THEME_CONFIGURATION_FILENAME
    if theme_config_path.is_file():
        try:
            data=json.loads(theme_config_path.read_text(encoding="utf-8"))
            candidate=str(((data.get("output") or {}).get("filename") or "")).strip()
            if _valid_cfg_filename_value(candidate):
                return candidate
        except Exception:
            pass
    cfgs=_top_level(theme_folder,'.cfg')
    if len(cfgs)==1:
        return cfgs[0].name
    return ""

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

def _prepare_app() -> UIL.ThemeLauncherApp:
    """Create the bundled launcher app, hidden, against the shared settings file."""
    app = UIL.ThemeLauncherApp()
    app.withdraw()
    app.settings_path = _shared_settings_path()
    app.freecad_executable_fallback_path = _shared_fallback_path()
    app.settings = _load_shared_settings()
    app._populate_ui_from_settings()
    return app


def _show_headless_error(message: str) -> None:
    print(str(message), file=sys.stderr)


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


def _launch(mode: str, force_all: bool=False) -> int:
    app = None
    try:
        if mode == 'creator':
            raw=_load_raw_settings()
            folder=str(raw.get('theme_folder','') or '').strip()
            if not folder:
                settings=_load_shared_settings(); folder=str(settings.theme_folder or '').strip()
            if not folder:
                raise UIL.LauncherError("Saved setting 'Theme Folder' is empty.")
            data=_prepare_creator_data(folder,force_all=force_all)
            cmd=[str(x) for x in data['cmd']]
            env={str(k):str(v) for k,v in data['env'].items()}
            runtime_root = Path(data['runtime_root'])
            theme_folder = Path(folder).expanduser().resolve()
            _shortcut_splash_log(runtime_root, 'Creator launch entered; folder=' + str(theme_folder))
            splash_source = theme_folder / 'splash' / 'freecadsplash.png'
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
                        cmd, suppressed_cfg = _prepare_suppressed_splash_launch(cmd, cfg_path, runtime_root)
                    except Exception:
                        UIL._stop_native_pixel_splash(splash_handle)
                        raise
                    _shortcut_splash_log(runtime_root, 'MODE: Custom splash; native FreeCAD splash suppressed for this launch only')
                else:
                    _shortcut_splash_log(runtime_root, 'FALLBACK: custom helper did not start')
            else:
                _shortcut_splash_log(runtime_root, 'No custom splash requested; CFG preference=' + splash_reason)
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
        settings = app.settings
        exe = str(settings.freecad_executable or '').strip()
        if not exe:
            raise UIL.LauncherError("Saved setting 'FreeCAD executable' is empty.")
        app.vars['freecad_executable'].set(exe)
        if mode == 'user':
            theme = str(settings.theme_file or '').strip()
            if not theme:
                raise UIL.LauncherError("Saved setting 'Theme' is empty.")
            p = Path(theme).expanduser()
            if not p.is_file():
                raise UIL.LauncherError(f'Saved Theme was not found:\n{p}')
            app.vars['user_mode'].set(True)
            app.vars['creator_mode'].set(False)
            app.vars['theme_file'].set(str(p.resolve()))
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
        source_user_cfg=app._resolve_creator_source_user_cfg(resolved_exe)
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

        env['FREECAD_USER_HOME']=str((runtime_root/'development_user_home').resolve())
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
            'source_user_cfg':str(source_user_cfg),'cfg_initialized':cfg_initialized,
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
        if options['use_external_configuration']:
            desired=str(raw.get('creator_cfg_filename','') or '').strip()
            if not desired:
                try:
                    desired=str((_load_shared_settings().creator_cfg_filename or '')).strip()
                except Exception: desired=''
            desired=_resolve_creator_cfg_filename(p,desired)
            if not desired:
                errors.append('External configuration is enabled, but no valid .cfg filename could be determined from Settings, theme-configuration.json, or a single top-level .cfg file.')
            else:
                expected=(p/desired).resolve(); cfg=str(expected)
                other=[x for x in _top_level(p,'.cfg') if x.resolve()!=expected]
                if other: errors.append('A differently named top-level .cfg exists: '+', '.join(x.name for x in other))
                if not expected.exists() and not (p/UIL.THEME_CONFIGURATION_FILENAME).is_file():
                    errors.append('Configured .cfg is missing and theme-configuration.json is not available to generate it.')
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

def _create_shortcut(mode: str, name: str, location: str, force_all: bool=False) -> int:
    app=None;cleanup_dir=None
    try:
        app=_prepare_app()
        raw=_load_raw_settings()
        if mode=='creator':
            folder=str(raw.get('theme_folder','') or app.settings.theme_folder or '').strip()
            if not folder: raise UIL.LauncherError("Saved setting 'Theme Folder' is empty.")
            source=Path(folder).expanduser().resolve()
            if not source.is_dir(): raise UIL.LauncherError(f'Theme Folder was not found:\n{source}')
            icon_path,cleanup_dir=app._resolve_shortcut_icon_for_source(source)
            target_path=Path(sys.executable).resolve()
            # Resolve the latest saved Develop-theme options each time the shortcut runs.
            shortcut_arguments=[str(Path(__file__).resolve()),'--launch-as-creator']
        else:
            theme=str(raw.get('theme_file','') or app.settings.theme_file or '').strip()
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
        if system=='windows':
            shortcut_path=location_path/f'{safe_name}.lnk';app._create_windows_shortcut(shortcut_path,target_path,shortcut_arguments,icon_path)
        elif system=='darwin':
            shortcut_path=location_path/f'{safe_name}.app';app._create_macos_shortcut(shortcut_path,target_path,shortcut_arguments,icon_path)
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
            return _create_shortcut(mode, args[i + 1], args[i + 2], force_all=force_all)
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
