#!/usr/bin/env python3
# Minimal offline splash controller. Safe in FreeCAD Python builds with broken ssl.py.
# Never import the full launcher here: it imports network and Tk modules at module load time.
from __future__ import annotations
import os, sys, re, time, secrets, subprocess
from pathlib import Path

class LauncherError(RuntimeError):
    pass

def _set_theme_profile_splash_disabled(cfg_path: Path, disabled: bool = True) -> None:
    """Disable FreeCAD's native splash only in this themed user.cfg.

    The theme profile owns its CFG; never touch the default FreeCAD user.cfg.
    Preserve other parameters and prefer a small textual change to rewriting XML.
    """
    import xml.etree.ElementTree as ET
    cfg_path = Path(cfg_path)
    if not cfg_path.is_file():
        raise LauncherError("The independent theme configuration is missing: " + str(cfg_path))
    # Keep the original FreeCAD XML untouched apart from the needed preference.
    raw = cfg_path.read_bytes()
    target_value = b'0' if disabled else b'1'
    match = re.search(rb'(<FCBool\s+Name="ShowSplasher"\s+Value=")[01]("\s*/>)', raw)
    if match:
        changed = raw[:match.start()] + match.group(1) + target_value + match.group(2) + raw[match.end():]
    else:
        root = ET.fromstring(raw)
        def ensure(parent, name):
            for child in parent.findall('FCParamGroup'):
                if child.get('Name') == name:
                    return child
            return ET.SubElement(parent, 'FCParamGroup', {'Name': name})
        node = root
        group_path = ('Root', 'BaseApp', 'Preferences', 'General')
        if root.tag == 'FCParamGroup' and root.get('Name') == 'Root':
            group_path = group_path[1:]
        for name in group_path:
            node = ensure(node, name)
        value = next((c for c in node.findall('FCBool') if c.get('Name') == 'ShowSplasher'), None)
        if value is None:
            value = ET.SubElement(node, 'FCBool', {'Name': 'ShowSplasher', 'Value': target_value.decode('ascii')})
        else:
            value.set('Value', target_value.decode('ascii'))
        changed = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    if changed != raw:
        cfg_path.write_bytes(changed)




def _splash_preference_allows_custom(cfg_path, theme_folder=None, marker_path=None):
    """Read ONLY the active FreeCAD CFG; JSON and historical marker do not override it.

    Absence of ShowSplasher follows FreeCAD's default of enabled. The profile CFG
    is authoritative so users can toggle splash in FreeCAD Preferences.
    """
    import xml.etree.ElementTree as ET
    cfg = Path(cfg_path)
    if not cfg.is_file():
        return True, 'active CFG not yet present; FreeCAD default applies'
    try:
        root = ET.parse(cfg).getroot()
        node = root
        names = ('Root', 'BaseApp', 'Preferences', 'General')
        if node.tag == 'FCParamGroup' and node.get('Name') == 'Root':
            names = names[1:]
        for name in names:
            node = next((child for child in node.findall('FCParamGroup')
                         if child.get('Name') == name), None)
            if node is None:
                return True, 'active CFG has no explicit ShowSplasher; FreeCAD default applies'
        item = next((child for child in node.findall('FCBool')
                     if child.get('Name') == 'ShowSplasher'), None)
        if item is not None and str(item.get('Value', '')).strip().lower() in ('0', 'false'):
            return False, 'active FreeCAD CFG sets ShowSplasher=0'
    except (OSError, ET.ParseError):
        return True, 'could not read ShowSplasher in active CFG; FreeCAD default applies'
    return True, 'active FreeCAD CFG permits splash'


def _suppress_native_splash_on_command(cmd):
    """Suppress FreeCAD native splash for this process only, never edit user CFG.

    FreeCAD's --set-config values run until the next option (--user-cfg).
    """
    result = list(cmd)
    token = 'ShowSplasher=0'
    if token in result:
        return result
    if '--set-config' in result:
        result.insert(result.index('--set-config') + 1, token)
    else:
        result[1:1] = ['--set-config', token]
    return result


def _prepare_suppressed_splash_launch(cmd, cfg_path, runtime_root):
    """Suppress native splasher for startup; restore user's preference in FreeCAD.

    FreeCAD's --set-config does not reliably override ShowSplasher in user.cfg.
    This uses the existing theme-owned CFG (never the normal FreeCAD profile),
    and appends a startup macro that restores the setting inside the new session.
    """
    cfg = Path(cfg_path).resolve()
    runtime = Path(runtime_root).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    allowed, reason = _splash_preference_allows_custom(cfg)
    if not allowed:
        return list(cmd), None
    if not cfg.is_file():
        raise LauncherError('Cannot suppress native splash: CFG missing: ' + str(cfg))
    _set_theme_profile_splash_disabled(cfg, True)
    macro = runtime / 'restore_theme_creator_splash_preference.FCMacro'
    macro.write_text("# Restore the FreeCAD splash preference after native startup is complete.\n# External Theme Creator temporarily disables it in the theme CFG to avoid a second splash.\nimport FreeCAD as App\nApp.ParamGet('User parameter:BaseApp/Preferences/General').SetBool('ShowSplasher', True)\n", encoding='utf-8')
    return list(cmd) + [str(macro)], cfg


def _restore_splash_preference_after_failed_launch(cfg_path):
    if cfg_path is not None:
        try:
            _set_theme_profile_splash_disabled(cfg_path, False)
        except Exception:
            pass


def _find_freecad_python(freecad_exe: Path) -> Path | None:
    """Find a Python interpreter associated with the selected FreeCAD install."""
    folder = Path(freecad_exe).resolve().parent
    names = ('pythonw.exe', 'python.exe') if os.name == 'nt' else ('python3', 'python')
    roots = [folder, folder / 'bin', folder.parent, folder.parent / 'bin',
             folder.parent / 'Library' / 'bin', folder.parent.parent / 'bin']
    running = Path(sys.executable).resolve() if sys.executable else None
    if running and running.is_file():
        # Prefer FreeCAD's actual running interpreter, when it belongs to this install.
        try:
            if running == Path(freecad_exe).resolve() or folder in running.parents or folder.parent in running.parents:
                roots.insert(0, running.parent)
        except Exception:
            pass
    seen = set()
    for base in roots:
        for name in names:
            candidate = base / name
            if str(candidate).lower() in seen:
                continue
            seen.add(str(candidate).lower())
            if candidate.is_file():
                return candidate
    return None


def _freecad_qt_platform_plugins(freecad_exe: Path, python_exe: Path) -> Path | None:
    """Find the Qt platform plugin shipped alongside the selected FreeCAD/PySide6.

    Do not accept an unrelated Qt installation from PATH or the parent process.
    """
    executable_dir = Path(freecad_exe).resolve().parent
    python_dir = Path(python_exe).resolve().parent
    bases = [python_dir, executable_dir, executable_dir.parent, python_dir.parent]
    tails = (
        # FreeCAD conda-forge/Windows layout: <installation>/lib/qt6/plugins.
        'lib/qt6/plugins/platforms',
        'Lib/site-packages/PySide6/plugins/platforms',
        'Lib/site-packages/PySide6/Qt/plugins/platforms',
        'Lib/site-packages/PySide6/Qt6/plugins/platforms',
        'lib/site-packages/PySide6/plugins/platforms',
        'plugins/platforms',
        'Library/plugins/platforms',
        'Library/lib/qt6/plugins/platforms',
        'share/qt6/plugins/platforms',
    )
    inspected = set()
    for base in bases:
        for tail in tails:
            location = (base / tail).resolve()
            key = str(location).casefold()
            if key in inspected:
                continue
            inspected.add(key)
            if (location / ('qwindows.dll' if os.name == 'nt' else 'libqxcb.so')).is_file():
                return location
    return None


def _splash_diagnostic(runtime_root: Path, message: str) -> None:
    """Record splash failures, but not routine successful launch information."""
    if not any(token in str(message).upper() for token in ('FALLBACK', 'ERROR', 'FAILED')):
        return
    try:
        import datetime
        runtime_root.mkdir(parents=True, exist_ok=True)
        with (runtime_root / 'splash-startup.log').open('a', encoding='utf-8') as out:
            out.write(datetime.datetime.now().isoformat(timespec='seconds') + ' ' + message + '\n')
    except Exception:
        pass


def _start_native_pixel_splash(freecad_exe: Path, image_path: Path, runtime_root: Path):
    """Start the splash and log why it succeeds/fails; returns process/stopfile or None."""
    runtime_root = Path(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    python_exe = _find_freecad_python(freecad_exe)
    helper = Path(__file__).resolve().parent / 'ExternalThemeCreatorStartupSplash.py'
    _splash_diagnostic(runtime_root, 'START executable=%s python=%s helper=%s image=%s' %
                       (freecad_exe, python_exe, helper, image_path))
    if python_exe is None or not helper.is_file():
        _splash_diagnostic(runtime_root, 'FALLBACK: Python interpreter or splash helper not found')
        return None
    plugin_dir = _freecad_qt_platform_plugins(freecad_exe, python_exe)
    _splash_diagnostic(runtime_root, 'QT PLATFORM plugin directory=' + str(plugin_dir or '<not found>'))
    if os.name == 'nt' and plugin_dir is None:
        _splash_diagnostic(runtime_root, 'FALLBACK: qwindows.dll not found in FreeCAD installation')
        return None
    splash_env = dict(os.environ)
    if plugin_dir:
        splash_env['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(plugin_dir)
        splash_env['QT_PLUGIN_PATH'] = str(plugin_dir.parent)
    # FreeCAD itself must retain its original environment; these overrides are
    # applied only to the standalone splash helper.
    splash_env.pop('QT_QPA_PLATFORM', None)
    stopfile = runtime_root / ('splash_stop_' + secrets.token_hex(10) + '.flag')
    log_path = runtime_root / ('splash-helper-' + stopfile.stem + '.tmp')
    try:
        kwargs = {'stdin': subprocess.DEVNULL, 'env': splash_env}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        with log_path.open('ab') as log:
            log.flush()
            proc = subprocess.Popen([str(python_exe), str(helper), str(image_path), str(stopfile)],
                                    stdout=log, stderr=subprocess.STDOUT, **kwargs)
        ready = Path(str(stopfile) + '.ready')
        deadline = time.monotonic() + 7.0
        while time.monotonic() < deadline:
            if ready.is_file() and proc.poll() is None:
                # The helper may still have the readiness file open on Windows.
                # Each launch uses a unique filename; no deletion is needed here.
                # Normal startup: helper output is no longer needed.
                try: log_path.unlink(missing_ok=True)
                except OSError: pass
                return proc, stopfile
            if proc.poll() is not None:
                _splash_diagnostic(runtime_root, 'FALLBACK: helper exited early code=%s see splash-helper.log' % proc.returncode)
                break
            time.sleep(0.05)
        else:
            _splash_diagnostic(runtime_root, 'FALLBACK: helper did not signal readiness in 7 seconds')
        try:
            stopfile.write_text('stop', encoding='ascii')
        except Exception:
            pass
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.terminate()
        except Exception:
            pass
        try:
            if log_path.is_file():
                with (runtime_root / 'splash-helper.log').open('ab') as saved:
                    saved.write(log_path.read_bytes())
                log_path.unlink(missing_ok=True)
        except OSError: pass
        for suffix in ('', '.ready', '.dpi.txt'):
            try: Path(str(stopfile) + suffix).unlink(missing_ok=True)
            except OSError: pass
        return None
    except Exception as exc:
        try:
            if 'proc' in locals() and proc.poll() is None:
                stopfile.write_text('stop', encoding='ascii')
                try: proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired: proc.terminate()
        except Exception: pass
        try:
            if log_path.is_file():
                with (runtime_root / 'splash-helper.log').open('ab') as saved:
                    saved.write(log_path.read_bytes())
                log_path.unlink(missing_ok=True)
        except OSError: pass
        _splash_diagnostic(runtime_root, 'FALLBACK: helper could not launch: %s: %s' %
                           (type(exc).__name__, exc))
        return None


def _stop_native_pixel_splash(handle) -> None:
    if not handle:
        return
    proc, stopfile = handle
    try: stopfile.write_text('stop', encoding='ascii')
    except Exception: pass
    # A short bounded wait allows the helper to process its stop signal before
    # removing handshake files. Never block FreeCAD startup indefinitely.
    try: proc.wait(timeout=3.0)
    except Exception: pass
    for suffix in ('', '.ready', '.dpi.txt'):
        try: Path(str(stopfile) + suffix).unlink(missing_ok=True)
        except OSError: pass
    try: (stopfile.parent / ('splash-helper-' + stopfile.stem + '.tmp')).unlink(missing_ok=True)
    except OSError: pass

