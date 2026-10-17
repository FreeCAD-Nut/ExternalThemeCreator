from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import traceback
from pathlib import Path

try:
    import FreeCAD as App
except Exception:
    App = None

_LOADED = {}
_LAST_FOLDER = None

KNOWN = {
    'property_editor_no_grid_v8.py': {
        'install': 'nut_grid_install',
        'uninstall': 'nut_grid_uninstall',
        'reload': None,
    },
    'task_header_arrows_v10.py': {
        'install': 'nut_task_arrows_install',
        'uninstall': 'nut_task_arrows_uninstall',
        'reload': 'nut_task_arrows_reload',
    },
}


def _log(message: str) -> None:
    text = f'External Theme Creator scripts: {message}'
    try:
        if App is not None:
            App.Console.PrintMessage(text + '\n')
    except Exception:
        pass
    folder = _LAST_FOLDER or _folder_from_environment()
    if folder:
        try:
            runtime = Path(folder) / '.ExternalThemeCreator_runtime'
            runtime.mkdir(parents=True, exist_ok=True)
            with (runtime / 'theme-scripts.log').open('a', encoding='utf-8') as f:
                f.write(text + '\n')
        except Exception:
            pass


def _folder_from_environment():
    raw = str(os.environ.get('EXTERNAL_THEME_CREATOR_THEME_FOLDER', '') or '').strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_dir():
            return p.resolve()
    return None


def _hook_map(path: Path, module):
    known = KNOWN.get(path.name.lower()) or KNOWN.get(path.name)
    if known:
        return dict(known)
    # Generic scripts are still loaded. Conventional lifecycle hooks are optional.
    return {
        'install': 'theme_install' if hasattr(module, 'theme_install') else ('install' if hasattr(module, 'install') else None),
        'uninstall': 'theme_uninstall' if hasattr(module, 'theme_uninstall') else ('uninstall' if hasattr(module, 'uninstall') else None),
        'reload': 'theme_reload' if hasattr(module, 'theme_reload') else ('reload' if hasattr(module, 'reload') else None),
    }


def _call(module, name, label):
    if not name:
        return True
    fn = getattr(module, name, None)
    if not callable(fn):
        _log(f'{label}: hook {name} is not callable; skipped')
        return False
    fn()
    _log(f'{label}: {name} succeeded')
    return True


def _module_name(path: Path):
    digest = hashlib.sha1(str(path.resolve()).encode('utf-8', 'replace')).hexdigest()[:12]
    return f'_theme_creator_script_{digest}'


def _unload_record(record):
    path = record['path']
    module = record['module']
    hooks = record['hooks']
    try:
        _call(module, hooks.get('uninstall'), path.name)
    except Exception as exc:
        _log(f'{path.name}: uninstall failed: {exc}\n{traceback.format_exc()}')
    try:
        sys.modules.pop(record['module_name'], None)
    except Exception:
        pass


def uninstall_all() -> None:
    for record in list(_LOADED.values()):
        _unload_record(record)
    _LOADED.clear()


def install_from_folder(folder=None) -> int:
    global _LAST_FOLDER
    p = Path(folder).expanduser().resolve() if folder else _folder_from_environment()
    if p is None or not p.is_dir():
        _log('no valid Theme Folder is available; no scripts loaded')
        return 0
    _LAST_FOLDER = p
    scripts = p / 'scripts'
    if not scripts.is_dir():
        _log(f'optional scripts folder not found: {scripts}')
        return 0

    count = 0
    for path in sorted((x for x in scripts.iterdir() if x.is_file() and x.suffix.lower() == '.py'), key=lambda x: x.name.lower()):
        try:
            key = str(path.resolve())
            if key in _LOADED:
                _unload_record(_LOADED.pop(key))
            module_name = _module_name(path)
            spec = importlib.util.spec_from_file_location(module_name, str(path))
            if spec is None or spec.loader is None:
                raise RuntimeError('could not create a Python module spec')
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            hooks = _hook_map(path, module)
            record = {'path': path, 'module': module, 'module_name': module_name, 'hooks': hooks}
            _LOADED[key] = record
            _log(f'{path.name}: loaded successfully')
            try:
                _call(module, hooks.get('install'), path.name)
            except Exception as exc:
                _log(f'{path.name}: installer failed: {exc}\n{traceback.format_exc()}')
            count += 1
        except Exception as exc:
            _log(f'{path.name}: load failed: {exc}\n{traceback.format_exc()}')
    _log(f'completed script load from {scripts}; files loaded: {count}')
    return count


def reload_all(reason='manual') -> int:
    folder = _LAST_FOLDER or _folder_from_environment()
    if folder is None:
        return 0
    reason = str(reason or 'manual').lower()
    if reason == 'icons':
        refreshed = 0
        for record in list(_LOADED.values()):
            hook = record['hooks'].get('reload')
            if not hook:
                continue
            try:
                if _call(record['module'], hook, record['path'].name):
                    refreshed += 1
            except Exception as exc:
                _log(f"{record['path'].name}: artwork reload failed: {exc}\n{traceback.format_exc()}")
        return refreshed

    # QSS reload and explicit script reloads perform a clean uninstall/re-exec/install.
    uninstall_all()
    return install_from_folder(folder)


def status():
    return {
        'theme_folder': str(_LAST_FOLDER or _folder_from_environment() or ''),
        'loaded_scripts': [record['path'].name for record in _LOADED.values()],
    }
