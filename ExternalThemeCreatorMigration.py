"""Non-destructive migration for External Theme Creator v0.9.73.

Old directories are retained as backup. Never merge different runtime profiles.
"""
from pathlib import Path
import os
import platform
import shutil
import tempfile

OLD_APP = "UI Launcher"
NEW_APP = "External Theme Creator"
OLD_RUNTIME = ".UI_Launcher_runtime"
NEW_RUNTIME = ".ExternalThemeCreator_runtime"
OLD_SETTINGS = "UI_Launcher_settings.json"
NEW_SETTINGS = "ExternalThemeCreator_settings.json"


def _base():
    system = platform.system().lower()
    if system == "windows":
        return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    if system == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def _copy_once(old, new):
    old, new = Path(old), Path(new)
    if new.exists() or not old.exists():
        return new
    new.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".etc-migrate-", dir=str(new.parent)))
    try:
        if old.is_dir():
            shutil.copytree(old, temporary, dirs_exist_ok=True)
            # No overwrites: if another process created new meanwhile, keep its state.
            if not new.exists():
                temporary.rename(new)
        else:
            target = temporary / old.name
            shutil.copy2(old, target)
            if not new.exists():
                target.rename(new)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    return new


def application_dir():
    legacy = _base() / OLD_APP
    current = _base() / NEW_APP
    _copy_once(legacy, current)
    if current.exists():
        legacy_settings = current / OLD_SETTINGS
        _copy_once(legacy_settings, current / NEW_SETTINGS)
        legacy_mirror = current / "ThemeCreatorLauncher"
        if legacy_mirror.exists():
            _copy_once(legacy_mirror / OLD_SETTINGS, legacy_mirror / NEW_SETTINGS)
    return current


def theme_runtime(folder):
    folder = Path(folder).expanduser().resolve()
    old, new = folder / OLD_RUNTIME, folder / NEW_RUNTIME
    _copy_once(old, new)
    return new
