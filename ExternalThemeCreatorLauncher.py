#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
External Theme Creator (bundled legacy launcher engine)
Cross-platform (Windows / macOS / Linux)

What it does:
- Lets the user choose a FreeCAD executable.
- Lets the user choose a Theme Folder.
- If the Theme Folder contains a .cfg file, it is treated as user.cfg.
- If the Theme Folder contains a .qss file, it is treated as the stylesheet to apply.
- If the Theme Folder contains freecadsplash.png, it is treated as the splash image override.
- If the Theme Folder contains icon files, or icons/ / Icons/ / images/ / Images/ folders,
  it can be used as FreeCAD's external icon theme source.
- Launches FreeCAD with --user-cfg pointing directly to the persistent theme-specific .cfg file.
- Redirects FREECAD_USER_HOME to a runtime user-home when needed for splash support and helper macro support.
- Saves launcher settings in a local JSON file next to this script.

This avoids overwriting the user's default FreeCAD configuration.
"""

from __future__ import annotations


import base64
import hashlib
import io
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import sys
import time
import tkinter as tk
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import zipfile
import xml.etree.ElementTree as ET
from typing import Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
# Import ssl lazily: some FreeCAD 26.3 builds have incompatible ssl.py/_ssl.

try:
    import certifi  # type: ignore
except Exception:  # pragma: no cover - fallback when certifi is unavailable
    certifi = None

APP_NAME = "External Theme Creator"
LEGACY_STORAGE_NAME = "External Theme Creator"  # Existing profiles, settings and keys must remain readable.
APP_VERSION = "1.52.15"
SETTINGS_FILE = "ExternalThemeCreator_settings.json"
RUNTIME_DIR_NAME = ".ExternalThemeCreator_runtime"
DEFAULT_SHORTCUT_ICONS_DIR_NAME = "Default_Shortcut_Icons"
CC_LICENSES_DIR_NAME = "CC_Licenses"
LICENSE_FILE_NAME = "License.lic"
THEME_LICENSE_RELPATH = "license/License.lic"
CUSTOM_LICENSE_OPTION = "Custom License"
CUSTOM_LICENSE_BRIEF_RELPATH = "license/License-brief.lic"
DEFAULT_LICENSE_NOTICE_BRIEF = 'Unless otherwise stated, the original icons, splash screens, images, and other artwork included in this *.fctheme package are subject to the terms of the included license'
DEFAULT_LICENSE_NOTICE = """License Notice

This package may contain materials under different licenses.

Unless otherwise stated, the original icons, splash screens, images, and other artwork included in this *.fctheme package are subject to the terms of the included license.

Stylesheets, FreeCAD configuration files, scripts, and other code-like files are not covered by the included license unless explicitly stated in the relevant file, folder, or accompanying notice.

Any third-party materials included in this package remain subject to their own respective license terms."""
LICENSE_PRESET_DETAILS = {
    'LGPL': {"filename": "LGPL-2.1-or-later.lic", "brief": 'You may use, copy, modify, and redistribute the licensed work under GNU LGPL version 2.1 or any later version. Preserve copyright and license notices, and comply with applicable source-code and relinking requirements when distributing covered software.'},
    "CC BY-ND 4.0": {
        "filename": "CC BY-ND 4.0.lic",
        "brief": "Credit must be given to the creator. No derivatives or adaptations of the licensed work are permitted.",
    },
    "CC BY-SA 4.0": {
        "filename": "CC BY-SA 4.0.lic",
        "brief": "Credit must be given to the creator. Adaptations must be shared under the same license terms.",
    },
    "CC_BY_4.0": {
        "filename": "CC_BY_4.0.lic",
        "brief": "Credit must be given to the creator.",
    },
    "CC_BY-NC_4.0": {
        "filename": "CC_BY-NC_4.0.lic",
        "brief": "Credit must be given to the creator. Only noncommercial use of the licensed work is permitted.",
    },
    "CC_BY-NC-ND_4.0": {
        "filename": "CC_BY-NC-ND_4.0.lic",
        "brief": "Credit must be given to the creator. Only noncommercial use of the licensed work is permitted. No derivatives or adaptations of the licensed work are permitted.",
    },
    "CC_BY-NC-SA_4.0": {
        "filename": "CC_BY-NC-SA_4.0.lic",
        "brief": "Credit must be given to the creator. Only noncommercial use of the licensed work is permitted. Adaptations must be shared under the same license terms.",
    },
}
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 700
RELOAD_MACRO_NAME = "ReloadExternalIconTheme.FCMacro"
SUPPORTED_ICON_EXTENSIONS = {".svg", ".png", ".xpm", ".ico", ".icns"}
EXPORTABLE_THEME_EXTENSIONS = {".svg", ".png", ".qss", ".json", ".ico", ".icns", ".lic", ".py"}
THEME_PACKAGE_TYPE = "freecad_ui_theme"
THEME_SCHEMA_VERSION = "1.0"
THEME_PAYLOAD_ENCRYPTION = "launcher_v1"
THEME_PACKAGE_EXTENSION = ".fctheme"
THEME_PACKAGE_OPTION_COMPLETE = "Complete Theme"
THEME_PACKAGE_OPTION_ARTWORK_ONLY = "Artwork Only"
THEME_PACKAGE_MODE_COMPLETE = "complete_theme"
THEME_PACKAGE_MODE_ARTWORK_ONLY = "artwork_only"
EXTERNAL_ASSET_METADATA_FILE = "external_assets.json"


def _is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resource_base_dir() -> Path:
    if _is_frozen_app():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _launcher_entry_path() -> Path:
    if _is_frozen_app():
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def _current_macos_app_bundle() -> Path | None:
    if platform.system().lower() != "darwin":
        return None
    executable_path = _launcher_entry_path()
    for candidate in [executable_path, *executable_path.parents]:
        if candidate.suffix.lower() == ".app":
            return candidate
    return None


def _settings_storage_path(base_dir: Path) -> Path:
    if _is_frozen_app():
        return _app_config_base_dir() / SETTINGS_FILE
    return base_dir / SETTINGS_FILE


def _freecad_executable_fallback_path(base_dir: Path) -> Path:
    if _is_frozen_app():
        return _app_config_base_dir() / "freecad_executable.txt"
    return base_dir / "freecad_executable.txt"


def _resolve_macos_app_executable(app_path: Path) -> Path | None:
    contents_macos = app_path / "Contents" / "MacOS"
    preferred_names = ["FreeCAD", "freecad"]
    for name in preferred_names:
        candidate = contents_macos / name
        if candidate.exists() and candidate.is_file():
            return candidate
    if contents_macos.exists() and contents_macos.is_dir():
        for child in sorted(contents_macos.iterdir(), key=lambda p: p.name.lower()):
            if child.is_file() and os.access(child, os.X_OK):
                return child
    return None


def _normalize_freecad_executable_path(path_text: str | Path | None) -> Path | None:
    if path_text is None:
        return None
    raw_text = str(path_text).strip()
    if not raw_text:
        return None
    candidate = Path(raw_text).expanduser()
    if platform.system().lower() == "darwin" and candidate.suffix.lower() == ".app":
        resolved = _resolve_macos_app_executable(candidate)
        return resolved if resolved is not None else candidate
    return candidate


def _autodetect_freecad_executable_path() -> Path | None:
    system = platform.system().lower()
    seen: set[str] = set()
    candidates: list[Path] = []

    def _add(candidate: str | Path | None) -> None:
        if candidate is None:
            return
        try:
            resolved = _normalize_freecad_executable_path(candidate)
        except Exception:
            return
        if resolved is None:
            return
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    for name in ("FreeCAD.exe", "FreeCAD", "freecad"):
        try:
            which_path = shutil.which(name)
        except Exception:
            which_path = None
        _add(which_path)

    if system == "windows":
        search_roots: list[Path] = []
        for env_name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            value = os.environ.get(env_name)
            if value:
                search_roots.append(Path(value))
        patterns = (
            "FreeCAD*/bin/FreeCAD.exe",
            "FreeCAD */bin/FreeCAD.exe",
            "FreeCAD/bin/FreeCAD.exe",
            "FreeCAD*/FreeCAD.exe",
            "FreeCAD */FreeCAD.exe",
        )
        for root in search_roots:
            try:
                for pattern in patterns:
                    for match in sorted(root.glob(pattern)):
                        _add(match)
            except Exception:
                continue
    elif system == "darwin":
        for candidate in (
            Path('/Applications/FreeCAD.app'),
            Path.home() / 'Applications' / 'FreeCAD.app',
        ):
            _add(candidate)
    elif system == "linux":
        for candidate in (
            Path.home() / 'Applications' / 'FreeCAD.AppImage',
            Path.home() / 'Desktop' / 'FreeCAD.AppImage',
            Path('/opt/FreeCAD/bin/FreeCAD'),
            Path('/usr/bin/freecad'),
            Path('/usr/local/bin/freecad'),
        ):
            _add(candidate)

    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return None
    existing.sort(key=lambda item: (item.name.lower(), str(item).lower()))
    return existing[0]


def _ensure_linux_appimage_executable(appimage_path: Path) -> None:
    try:
        mode = appimage_path.stat().st_mode
        if not (mode & 0o111):
            appimage_path.chmod(mode | 0o111)
    except Exception:
        pass


def _is_linux_appimage_path(path: Path | str | None) -> bool:
    if path is None:
        return False
    try:
        return str(path).lower().endswith('.appimage')
    except Exception:
        return False


def _shell_join(parts: list[str]) -> str:
    if platform.system().lower() == "windows":
        return subprocess.list2cmdline(parts)
    return " ".join(shlex.quote(part) for part in parts)


def _desktop_exec_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\\"')
    return f'"{escaped}"'


def _persistent_shortcut_icon_path(shortcut_path: Path, source_icon_path: Path) -> Path:
    icon_store_dir = _app_config_base_dir() / "Shortcut_Icons"
    icon_store_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", shortcut_path.stem).strip("._") or "FreeCAD"
    path_key = hashlib.sha1(str(shortcut_path.expanduser()).encode("utf-8")).hexdigest()[:10]
    suffix = source_icon_path.suffix.lower() or ".png"
    return icon_store_dir / f"{safe_name}_{path_key}{suffix}"


def _make_shortcut_icon_persistent(shortcut_path: Path, icon_path: Path | None) -> Path | None:
    if icon_path is None or not icon_path.exists():
        return None
    persistent_icon_path = _persistent_shortcut_icon_path(shortcut_path, icon_path)
    persistent_icon_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_path, persistent_icon_path)
    return persistent_icon_path


def _mark_linux_shortcut_trusted(shortcut_path: Path, icon_path: Path | None = None) -> None:
    try:
        os.chmod(shortcut_path, 0o755)
    except Exception:
        pass

    gio_path = shutil.which("gio")
    if not gio_path:
        return

    commands = [
        [gio_path, "set", "-t", "string", str(shortcut_path), "metadata::trusted", "yes"],
    ]
    if icon_path is not None and icon_path.exists():
        icon_uri = _path_to_file_uri(icon_path.resolve())
        commands.append([gio_path, "set", "-t", "string", str(shortcut_path), "metadata::custom-icon", icon_uri])

    for command in commands:
        try:
            subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass



def _applescript_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _run_macos_osascript(lines: list[str]) -> str | None:
    try:
        command = ["/usr/bin/osascript"]
        for line in lines:
            command.extend(["-e", line])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception:
        return None
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip().lower()
        if "user canceled" in stderr_text:
            return ""
        return None
    return (result.stdout or "").strip()


def _macos_choose_application_path(prompt: str, title: str) -> str | None:
    return _run_macos_osascript([
        f"set selectedApp to choose application with title {_applescript_quote(title)} with prompt {_applescript_quote(prompt)} as alias",
        "return POSIX path of selectedApp",
    ])


def _macos_choose_folder_path(prompt: str, default_location: str | None = None) -> str | None:
    command = f"set selectedFolder to choose folder with prompt {_applescript_quote(prompt)}"
    if default_location:
        command += f" default location (POSIX file {_applescript_quote(default_location)})"
    command += " showing package contents false"
    return _run_macos_osascript([command, "return POSIX path of selectedFolder"])


def _macos_choose_file_path(prompt: str, default_location: str | None = None) -> str | None:
    command = f"set selectedFile to choose file with prompt {_applescript_quote(prompt)}"
    if default_location:
        command += f" default location (POSIX file {_applescript_quote(default_location)})"
    command += " showing package contents false"
    return _run_macos_osascript([command, "return POSIX path of selectedFile"])

RELOAD_MACRO_CONTENT = """import FreeCADGui as Gui\nGui.reloadExternalIconTheme()\n"""
RELOAD_CONSOLE_COMMAND = "import FreeCADGui as Gui\nGui.reloadExternalIconTheme()"


@dataclass
class AppSettings:
    freecad_executable: str = ""
    creator_user_cfg: str = ""
    creator_cfg_filename: str = ""
    theme_folder: str = ""
    theme_file: str = ""
    launch_mode: str = "user"
    use_freecad_user_home: bool = True
    use_external_theme_stylesheet_assets: bool = True
    use_external_configuration: bool = True
    use_external_ui_scripts: bool = True
    enable_external_icon_theme: bool = True
    prefer_external_icons: bool = True
    close_after_freecad_launch: bool = True
    extra_cli_args: str = ""
    author_key_file: str = ""
    export_theme_name: str = ""
    export_theme_version: str = "1.0.0"
    export_author_name: str = ""
    export_freecad_version_tested: str = ""
    export_description: str = ""
    export_copyright: str = ""
    export_license: str = CUSTOM_LICENSE_OPTION
    export_license_terms: str = ""
    export_license_notice_brief: str = DEFAULT_LICENSE_NOTICE_BRIEF
    export_license_notice: str = DEFAULT_LICENSE_NOTICE
    export_theme_package: str = THEME_PACKAGE_OPTION_COMPLETE
    export_require_external_cfg: bool = False
    export_external_cfg_url: str = ""
    export_require_external_qss: bool = False
    export_external_qss_url: str = ""


def _filtered_app_settings_payload(data: dict[str, object]) -> dict[str, object]:
    allowed = {item.name for item in fields(AppSettings)}
    return {key: value for key, value in data.items() if key in allowed}


def _load_app_settings_from_path(settings_path: Path) -> AppSettings:
    raw_data = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise LauncherError(f"Saved settings file is not a JSON object:\n{settings_path}")
    filtered = _filtered_app_settings_payload(raw_data)
    defaults = asdict(AppSettings())
    defaults.update(filtered)
    return AppSettings(**defaults)


def _slugify_theme_id(theme_name: str) -> str:
    value = theme_name.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def _normalize_theme_package_value(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {THEME_PACKAGE_OPTION_ARTWORK_ONLY.lower(), THEME_PACKAGE_MODE_ARTWORK_ONLY}:
        return THEME_PACKAGE_OPTION_ARTWORK_ONLY
    return THEME_PACKAGE_OPTION_COMPLETE


def _theme_package_manifest_value(value: str | None) -> str:
    normalized = _normalize_theme_package_value(value)
    if normalized == THEME_PACKAGE_OPTION_ARTWORK_ONLY:
        return THEME_PACKAGE_MODE_ARTWORK_ONLY
    return THEME_PACKAGE_MODE_COMPLETE


def _is_artwork_only_theme_package(value: str | None) -> bool:
    return _theme_package_manifest_value(value) == THEME_PACKAGE_MODE_ARTWORK_ONLY


def _default_notice_values_for_theme_package(value: str | None) -> tuple[str, str]:
    if _is_artwork_only_theme_package(value):
        return "", ""
    return DEFAULT_LICENSE_NOTICE_BRIEF, DEFAULT_LICENSE_NOTICE


def _normalize_external_asset_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return raw
    parsed = urllib_parse.urlparse(raw)
    host = (parsed.netloc or "").lower()
    path_parts = [part for part in (parsed.path or "").split("/") if part]

    if host == "github.com" and len(path_parts) >= 5 and path_parts[2] == "blob":
        owner, repo, _blob, branch = path_parts[:4]
        remainder = "/".join(path_parts[4:])
        normalized_path = f"/{owner}/{repo}/{branch}/{remainder}"
        return urllib_parse.urlunparse(("https", "raw.githubusercontent.com", normalized_path, "", "", ""))

    if host in {"www.dropbox.com", "dropbox.com"}:
        query = urllib_parse.parse_qs(parsed.query, keep_blank_values=True)
        query["dl"] = ["1"]
        return urllib_parse.urlunparse(parsed._replace(query=urllib_parse.urlencode(query, doseq=True)))

    return raw


def _looks_like_html_bytes(data: bytes) -> bool:
    head = data[:2048].decode("utf-8", errors="ignore").lstrip().lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<html" in head[:256]


def _sanitize_xml_text_for_parse(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z_][A-Za-z0-9_.:-]*;)", "&amp;", text)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)
    return text


def _parse_cfg_xml_permissive(source_user_cfg: Path) -> tuple[ET.ElementTree, ET.Element]:
    try:
        tree = ET.parse(source_user_cfg)
        return tree, tree.getroot()
    except Exception as first_exc:
        raw_bytes = source_user_cfg.read_bytes()
        if _looks_like_html_bytes(raw_bytes):
            raise LauncherError(
                "The downloaded .cfg file appears to be an HTML page instead of a direct XML file.\n"
                f"Please use a direct-download URL for the .cfg file:\n{source_user_cfg}"
            ) from first_exc
        try:
            sanitized_text = _sanitize_xml_text_for_parse(raw_bytes.decode("utf-8-sig", errors="replace"))
            root = ET.fromstring(sanitized_text)
            return ET.ElementTree(root), root
        except Exception as second_exc:
            raise LauncherError(
                f"Could not parse the .cfg file as XML:\n{source_user_cfg}\n\n{second_exc}"
            ) from second_exc


def _external_asset_filename_from_url(url: str, expected_suffix: str) -> str:
    normalized = _normalize_external_asset_url(url)
    parsed = urllib_parse.urlparse(normalized)
    filename = Path(urllib_parse.unquote(parsed.path or "")).name.strip()
    if not filename:
        raise LauncherError(f"Could not determine a file name from URL:\n{url}")
    if Path(filename).suffix.lower() != expected_suffix.lower():
        raise LauncherError(f"The URL must point to a {expected_suffix} file:\n{url}")
    return filename

def _canonical_manifest_bytes(manifest: dict[str, object]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _payload_fernet_key() -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(b"External Theme Creator Theme Payload Key v1").digest())


def _count_suffixes(paths: list[str]) -> dict[str, int]:
    counts = {".svg": 0, ".png": 0, ".qss": 0, ".cfg": 0}
    for rel in paths:
        suffix = Path(rel).suffix.lower()
        if suffix in counts:
            counts[suffix] += 1
    return counts


def _cc_licenses_dir(base_dir: Path) -> Path:
    return base_dir / CC_LICENSES_DIR_NAME


def _license_options_for_dir(base_dir: Path) -> list[str]:
    license_dir = _cc_licenses_dir(base_dir)
    available = {path.stem for path in license_dir.glob('*.lic') if path.is_file()}
    ordered = [name for name, spec in LICENSE_PRESET_DETAILS.items() if Path(spec["filename"]).stem in available]
    extras = sorted(available - {Path(spec["filename"]).stem for spec in LICENSE_PRESET_DETAILS.values()}, key=str.lower)
    return ordered + extras + [CUSTOM_LICENSE_OPTION]


def _license_source_path(base_dir: Path, license_choice: str) -> Path | None:
    if license_choice == CUSTOM_LICENSE_OPTION:
        return None
    details = LICENSE_PRESET_DETAILS.get(license_choice)
    if not details:
        candidate = _cc_licenses_dir(base_dir) / f"{license_choice}.lic"
        return candidate if candidate.exists() else None
    candidate = _cc_licenses_dir(base_dir) / details["filename"]
    return candidate if candidate.exists() else None


def _default_license_brief_for_choice(license_choice: str) -> str:
    details = LICENSE_PRESET_DETAILS.get(license_choice)
    if details:
        return str(details.get("brief", ""))
    return ""


def _top_level_theme_license_relpath(theme_folder: Path) -> str:
    candidate = theme_folder / THEME_LICENSE_RELPATH
    return THEME_LICENSE_RELPATH if candidate.is_file() else ""


def _effective_export_file_list(scan: dict[str, object], theme_folder: Path, license_choice: str, theme_package: str = THEME_PACKAGE_OPTION_COMPLETE) -> list[str]:
    included_files = list(scan.get("included_files", []))
    included_files = [rel for rel in included_files if Path(rel).name.lower() != THEME_CONFIGURATION_SKIPPED_FILENAME.lower() and rel.lower() != CUSTOM_LICENSE_BRIEF_RELPATH.lower()]
    if _is_artwork_only_theme_package(theme_package):
        included_files = [
            rel for rel in included_files
            if Path(rel).suffix.lower() not in {".cfg", ".qss"}
            and Path(rel).name.lower() != THEME_CONFIGURATION_FILENAME.lower()
        ]
    if license_choice == CUSTOM_LICENSE_OPTION:
        custom_rel = _top_level_theme_license_relpath(theme_folder)
        if custom_rel and custom_rel not in included_files:
            included_files.append(custom_rel)
    elif license_choice and license_choice != CUSTOM_LICENSE_OPTION:
        if THEME_LICENSE_RELPATH not in included_files:
            included_files.append(THEME_LICENSE_RELPATH)
    if license_choice and CUSTOM_LICENSE_BRIEF_RELPATH not in included_files:
        included_files.append(CUSTOM_LICENSE_BRIEF_RELPATH)
    return sorted(set(included_files), key=str.lower)


def _detect_existing_license_choice(base_dir: Path, theme_folder: Path) -> str:
    license_path = theme_folder / THEME_LICENSE_RELPATH
    if not license_path.exists() or not license_path.is_file():
        return CUSTOM_LICENSE_OPTION
    try:
        current_bytes = license_path.read_bytes()
    except Exception:
        return CUSTOM_LICENSE_OPTION
    for option, details in LICENSE_PRESET_DETAILS.items():
        source_path = _cc_licenses_dir(base_dir) / details["filename"]
        try:
            if source_path.exists() and source_path.read_bytes() == current_bytes:
                return option
        except Exception:
            continue
    return CUSTOM_LICENSE_OPTION


def _detect_splash_relpath(paths: list[str]) -> str:
    if 'splash/freecadsplash.png' in paths:
        return 'splash/freecadsplash.png'
    preferred_exact = {"freecadsplash.png", "splash_image.png"}
    exact_matches = [rel for rel in paths if Path(rel).name.lower() in preferred_exact]
    if exact_matches:
        return sorted(exact_matches, key=lambda rel: rel.lower())[0]
    named_matches = [
        rel for rel in paths
        if Path(rel).suffix.lower() == ".png" and "splash" in Path(rel).stem.lower()
    ]
    if named_matches:
        return sorted(named_matches, key=lambda rel: rel.lower())[0]
    return ""


def _is_safe_relpath(rel: str) -> bool:
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        return False
    pure = Path(rel)
    if pure.is_absolute():
        return False
    parts = pure.parts
    if any(part == ".." for part in parts):
        return False
    if ":" in rel:
        return False
    return True


def _app_config_base_dir() -> Path:
    from ExternalThemeCreatorMigration import application_dir
    return application_dir()
    system = platform.system().lower()
    if system == "windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / LEGACY_STORAGE_NAME
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / LEGACY_STORAGE_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / LEGACY_STORAGE_NAME
    return Path.home() / ".config" / LEGACY_STORAGE_NAME


def _theme_state_dir(theme_id: str) -> Path:
    return _app_config_base_dir() / "Themes" / theme_id


def _theme_user_cfg_path(theme_id: str) -> Path:
    return _theme_state_dir(theme_id) / "user.cfg"


def _theme_external_assets_dir(theme_id: str) -> Path:
    return _theme_state_dir(theme_id) / "External_Assets"


def _theme_external_assets_metadata_path(theme_id: str) -> Path:
    return _theme_external_assets_dir(theme_id) / EXTERNAL_ASSET_METADATA_FILE


def _read_external_assets_metadata(theme_id: str) -> dict[str, object]:
    path = _theme_external_assets_metadata_path(theme_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_external_assets_metadata(theme_id: str, data: dict[str, object]) -> None:
    path = _theme_external_assets_metadata_path(theme_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_url_bytes(url: str, expected_suffix: str | None = None) -> bytes:
    normalized_url = _normalize_external_asset_url(url)
    request = urllib_request.Request(
        normalized_url,
        headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
    )
    ssl_context = None
    parsed = urllib_parse.urlparse(normalized_url)
    if parsed.scheme.lower() == "https" and certifi is not None:
        try:
            cafile = certifi.where()
            if cafile:
                import ssl
                ssl_context = ssl.create_default_context(cafile=cafile)
        except Exception:
            ssl_context = None
    try:
        with urllib_request.urlopen(request, timeout=30, context=ssl_context) as response:
            data = response.read()
    except urllib_error.HTTPError as exc:
        raise LauncherError(f"Download failed ({exc.code}) for:\n{url}") from exc
    except urllib_error.URLError as exc:
        cert_hint = ""
        reason_text = str(exc.reason) if getattr(exc, "reason", None) else str(exc)
        if parsed.scheme.lower() == "https" and "CERTIFICATE_VERIFY_FAILED" in reason_text and platform.system() == "Darwin":
            cert_hint = (
                "\n\nThe macOS app could not validate the HTTPS certificate chain. "
                "This build is expected to use the bundled certifi CA bundle; if the problem persists, rebuild the app "
                "with certifi installed so the CA bundle is included in the packaged runtime."
            )
        raise LauncherError(f"Could not download required external asset:\n{url}\n\n{exc}{cert_hint}") from exc

    if expected_suffix in {".cfg", ".qss"} and _looks_like_html_bytes(data):
        raise LauncherError(
            f"The URL did not return a direct {expected_suffix} file.\n"
            "Please use a direct-download link, not a normal web page URL.\n\n"
            f"URL:\n{url}\n\nResolved download URL:\n{normalized_url}"
        )
    return data

def _make_obscured_temp_dir() -> Path:
    path = Path(tempfile.gettempdir()) / f".uix_{secrets.token_hex(8)}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _is_safe_temporary_cleanup_dir(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        resolved = path.resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
    except Exception:
        return False
    if not resolved.exists() or not resolved.is_dir():
        return False
    if resolved == temp_root:
        return False
    try:
        resolved.relative_to(temp_root)
    except ValueError:
        return False
    return resolved.name.startswith(".uix_")


def _safe_rmtree(path: Path | None) -> bool:
    if not _is_safe_temporary_cleanup_dir(path):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def _require_crypto():
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        return Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey
    except Exception as exc:
        raise LauncherError("The Python package 'cryptography' is required for Author Key, Export Theme, and Launch from Theme features.") from exc


def _load_author_private_key(private_key_path: Path):
    Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise LauncherError("The selected Author Key is not an Ed25519 private key.")
    public_key = private_key.public_key()
    public_bytes_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fingerprint_hex = public_bytes_raw.hex().upper()
    fingerprint = "-".join(fingerprint_hex[i:i + 4] for i in range(0, min(len(fingerprint_hex), 32), 4))
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem, fingerprint


def _verify_signature(manifest: dict[str, object], public_pem: bytes, signature_b64: str) -> None:
    Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
    public_key = serialization.load_pem_public_key(public_pem)
    if not isinstance(public_key, Ed25519PublicKey):
        raise LauncherError("Theme package public key is not a valid Ed25519 public key.")
    signature = base64.b64decode(signature_b64.encode("ascii"))
    public_key.verify(signature, _canonical_manifest_bytes(manifest))


def _encrypt_payload(payload_bytes: bytes) -> bytes:
    Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
    return Fernet(_payload_fernet_key()).encrypt(payload_bytes)


def _decrypt_payload(payload_bytes: bytes) -> bytes:
    Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
    return Fernet(_payload_fernet_key()).decrypt(payload_bytes)



class LauncherError(Exception):
    pass


class CollapsibleSection(ttk.Frame):
    def __init__(self, parent, title: str, expanded: bool = False, on_toggle=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self._expanded = expanded
        self._title = title
        self._on_toggle = on_toggle
        self.columnconfigure(0, weight=1)

        self.toggle_button = ttk.Button(self, text="", command=self.toggle)
        self.toggle_button.grid(row=0, column=0, sticky="ew")

        self.body = ttk.Frame(self, padding=(10, 8, 10, 10))
        self.body.grid(row=1, column=0, sticky="ew")
        self.body.columnconfigure(0, weight=1)

        self._sync()

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._sync()
        if self._on_toggle is not None:
            self._on_toggle()

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._sync()
        if self._on_toggle is not None:
            self._on_toggle()

    def _sync(self) -> None:
        symbol = "▼" if self._expanded else "▶"
        self.toggle_button.configure(text=f"{symbol} {self._title}")
        if self._expanded:
            self.body.grid()
        else:
            self.body.grid_remove()


THEME_CONFIGURATION_FILENAME = "theme-configuration.json"
THEME_CONFIGURATION_SKIPPED_FILENAME = "theme-configuration-skipped.json"
THEME_CONFIGURATION_SCHEMA = "ui-launcher-theme-configuration"
THEME_CONFIGURATION_VERSION = 3


def _cfg_parameter_map(source_cfg: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Return editable FreeCAD parameters keyed by (group path, parameter name)."""
    _tree, root = _parse_cfg_xml_permissive(source_cfg)
    result: dict[tuple[str, str], dict[str, str]] = {}

    def walk(node: ET.Element, groups: list[str]) -> None:
        for child in node:
            if child.tag == "FCParamGroup":
                name = str(child.attrib.get("Name", "")).strip()
                walk(child, groups + ([name] if name else []))
                continue
            name = str(child.attrib.get("Name", "")).strip()
            if not name:
                continue
            if child.tag == "FCText":
                value = child.text or ""
            else:
                value = str(child.attrib.get("Value", ""))
            path = "/".join(groups)
            result[(path, name)] = {
                "path": path,
                "name": name,
                "type": child.tag,
                "value": value,
            }

    walk(root, [])
    return result


def _cfg_custom_toolbar_groups(source_cfg: Path) -> dict[str, list[dict[str, str]]]:
    """Return complete Custom_* toolbar groups with child order preserved."""
    _tree, root = _parse_cfg_xml_permissive(source_cfg)
    result: dict[str, list[dict[str, str]]] = {}

    def walk(node: ET.Element, groups: list[str]) -> None:
        for child in node:
            if child.tag != "FCParamGroup":
                continue
            name = str(child.attrib.get("Name", "")).strip()
            next_groups = groups + ([name] if name else [])
            path = "/".join(next_groups)
            parent_path_l = "/".join(groups).lower()
            if name.lower().startswith("custom_") and parent_path_l.endswith("/toolbar"):
                items: list[dict[str, str]] = []
                for item in child:
                    if item.tag == "FCParamGroup":
                        # Custom toolbar definitions are expected to contain parameters only.
                        # Leave unexpected nested structures to the normal review path.
                        continue
                    item_name = str(item.attrib.get("Name", "")).strip()
                    if not item_name:
                        continue
                    value = (item.text or "") if item.tag == "FCText" else str(item.attrib.get("Value", ""))
                    items.append({"type": item.tag, "name": item_name, "value": value})
                result[path] = items
            walk(child, next_groups)

    walk(root, [])
    return result


def _toolbar_items_signature(items: list[dict[str, str]] | None) -> tuple[tuple[str, str, str], ...] | None:
    if items is None:
        return None
    return tuple((item.get("type", ""), item.get("name", ""), item.get("value", "")) for item in items)


UI_CONFIGURATION_CATEGORIES = (
    "appearance",
    "startup",
    "layout",
    "toolbars",
    "menus",
    "panels",
    "navigation_view",
    "other_ui",
)

_UI_TRANSIENT_NAMES = {
    "geometry", "windowstaterestored", "maximized",
    "fileopensavepath", "lastmodule", "lasttabindex", "recentfiles",
    "stylesheet", "overlayactivestylesheet",
}


def _theme_ui_category(parameter: dict[str, str]) -> str | None:
    """Return the human-readable UI category for a portable theme setting.

    This intentionally errs on the side of excluding application/modeling state.
    Unknown settings are not exported merely because two CFG files differ.
    """
    path = parameter.get("path", "")
    name = parameter.get("name", "")
    path_l = path.lower()
    name_l = name.lower()
    value = parameter.get("value", "")

    # Explicit rules take precedence over broad path/category rules.
    # QSS is a separate theme asset and transient window/session values are not
    # portable theme configuration.
    if name_l in _UI_TRANSIENT_NAMES:
        return None
    if name_l.endswith("stylesheet") or "stylesheet" in name_l:
        return None

    # Start-page visibility is an intentional startup UI choice even though it
    # lives under the otherwise broad Preferences/Mod branch.
    if path_l.rstrip("/").endswith("/preferences/mod/start") and name_l == "showonstartup":
        return "startup"

    # Qt's serialized main-window state is theme-relevant in FreeCAD: it carries
    # dock/tab relationships (including Model + Tasks) and toolbar/dock placement.
    # This explicit include must run before the generic large-value rule.
    if path_l.rstrip("/").endswith("/preferences/mainwindow") and name_l == "mainwindowstate":
        return "layout"

    # Pixel geometry remembered from a particular window/display is not portable.
    # Do not confuse this with dock/toolbar placement, which remains theme-relevant.
    if "dockwindows/overlay" in path_l and name_l in {"width", "height"}:
        return None
    if any(token in path_l for token in ("/preferences/treeview", "/preferences/propertyview", "/preferences/comboview")) and name_l.startswith("columnsize"):
        return None

    # Unknown large/serialized values are not silently accepted. They remain
    # visible as Unclassified in the review file rather than being presumed
    # transient merely because their representation is opaque.
    if len(value) > 512:
        return None

    # Toolbar definitions and persistent toolbar placement are UI by design.
    if "/toolbar" in path_l or "toolbars" in path_l or "persistenttoolbars" in path_l:
        return "toolbars"

    # Dock windows, tree/property/combo panels and overlay placement.
    if "dockwindows" in path_l or "treeview" in path_l or "propertyview" in path_l or "comboview" in path_l:
        return "panels"

    # Main-window preferences: retain only explicit appearance/UI controls.
    if path_l.endswith("/preferences/mainwindow") or path_l == "preferences/mainwindow":
        if name_l in {"qtstyle", "theme", "tiledbackground", "inputhintenabled", "quickmeasureenabled", "wsposition"}:
            return "appearance" if name_l in {"qtstyle", "theme", "tiledbackground"} else "other_ui"
        return None

    # General preferences are mostly application behavior. Keep only settings
    # that explicitly describe visible chrome.
    if path_l.endswith("/preferences/general") or path_l == "preferences/general":
        if name_l == "toolbariconsize":
            return "toolbars"
        if name_l in {"showsplasher", "showtaskwatcher", "enablecursorblinking"}:
            return "other_ui"
        return None

    # FreeCAD's View group mixes rendering, navigation and visual UI settings.
    # Only retain names that clearly concern visible appearance/navigation.
    if path_l.endswith("/preferences/view") or "/preferences/view/" in path_l:
        appearance_tokens = (
            "color", "font", "textsize", "iconsize", "markersize", "background",
            "linewidth", "pointsize", "transparency", "shininess", "highlight",
            "selection", "constraint", "sketch", "axis", "crosshair",
        )
        navigation_tokens = (
            "navigation", "navicube", "orbit", "zoom", "rotation", "perspective",
            "orthographic", "pickradius", "longpress", "preselection", "cornercoord",
        )
        if name_l.startswith("dockoverlay"):
            return "panels"
        if any(token in name_l for token in appearance_tokens):
            return "appearance"
        if any(token in name_l for token in navigation_tokens):
            return "navigation_view"
        return None

    # Menu-specific configuration, if FreeCAD stores it in a dedicated branch.
    if "/menu" in path_l or "menus" in path_l:
        return "menus"

    # Explicit UI branches that do not fit the groups above remain reviewable.
    if any(token in path_l for token in ("/mainwindow/", "/preferences/ui", "/preferences/gui")):
        return "other_ui"

    return None


def _skipped_configuration_classification(parameter: dict[str, str]) -> tuple[str, str]:
    """Explain why a changed CFG parameter was not accepted as a theme UI instruction."""
    path_l = parameter.get("path", "").lower()
    name_l = parameter.get("name", "").lower()
    value = parameter.get("value", "")

    if name_l == "stylesheet" or name_l.endswith("stylesheet") or "stylesheet" in name_l:
        return "External Theme Assets", "Stylesheet content is supplied separately as the theme QSS."
    if "dockwindows/overlay" in path_l and name_l in {"width", "height"}:
        return "Transient UI State", "Saved overlay dock width/height is display-dependent pixel geometry; dock and toolbar placement itself remains theme-relevant."
    if any(token in path_l for token in ("/preferences/treeview", "/preferences/propertyview", "/preferences/comboview")) and name_l.startswith("columnsize"):
        return "Transient UI State", "Saved panel column width is display/window-dependent pixel geometry and is not portable theme configuration."
    if name_l in _UI_TRANSIENT_NAMES or name_l in {"geometry", "windowstaterestored", "maximized", "wsposition"}:
        return "Transient UI State", "Window/session geometry or state is transient or machine-layout dependent and is not portable theme configuration."
    if len(value) > 512:
        return "Unclassified", "Large or serialized value is not understood well enough to classify automatically; review it rather than assuming it is transient or non-UI."
    if any(token in name_l for token in ("path", "directory", "filename", "recent")) or any(token in path_l for token in ("recent", "filedialog", "macro")):
        return "Machine/User-specific", "Setting appears to contain a user/machine-specific path, recent item, or local state."
    if any(token in path_l for token in (
        "/mod/", "/preferences/import", "/preferences/export", "/preferences/units",
        "/preferences/document", "/preferences/objects", "/preferences/part",
        "/preferences/sketch", "/preferences/mesh", "/preferences/draft",
    )):
        return "Non-UI Preferences", "Setting belongs to application, workbench, modeling, document, import/export, or other non-UI preferences."
    return "Unclassified", "Changed setting was not recognized by the current UI classifier. Review it manually if it should be part of the theme."


def _reviewable_skipped_instruction(before: dict[str, str] | None, after: dict[str, str] | None, category: str, reason: str) -> dict[str, object]:
    source = after or before or {}
    item: dict[str, object] = {
        "reason": reason,
        "action": "remove" if after is None else "set",
        "path": source.get("path", ""),
        "name": source.get("name", ""),
    }
    if after is not None:
        item["type"] = after.get("type", "")
        value = after.get("value", "")
        # Do not reproduce QSS or huge serialized payloads in the review file.
        if category in {"External Theme Assets", "Large/Opaque Values"} and len(value) > 512:
            item["value"] = f"<value omitted: {len(value)} characters>"
            item["value_length"] = len(value)
        else:
            item["value"] = value
    return item


def _generate_theme_configuration(default_cfg: Path, custom_cfg: Path, output_filename: str) -> tuple[dict[str, object], dict[str, object]]:
    default_params = _cfg_parameter_map(default_cfg)
    custom_params = _cfg_parameter_map(custom_cfg)
    default_toolbars = _cfg_custom_toolbar_groups(default_cfg)
    custom_toolbars = _cfg_custom_toolbar_groups(custom_cfg)
    categories: dict[str, list[dict[str, str]]] = {name: [] for name in UI_CONFIGURATION_CATEGORIES}
    skipped_order = [
        "Unclassified", "Non-UI Preferences", "Transient UI State",
        "Machine/User-specific", "External Theme Assets", "Large/Opaque Values",
    ]
    skipped_categories: dict[str, list[dict[str, object]]] = {name: [] for name in skipped_order}

    # Custom toolbars are ordered structures: XML child order determines command
    # and separator order. Represent a changed toolbar atomically so applying the
    # theme can rebuild it exactly instead of treating its children as an unordered
    # collection of independent set/remove operations.
    structural_toolbar_paths: set[str] = set()
    for toolbar_path in sorted(set(default_toolbars) | set(custom_toolbars), key=str.lower):
        before_items = default_toolbars.get(toolbar_path)
        after_items = custom_toolbars.get(toolbar_path)
        if _toolbar_items_signature(before_items) == _toolbar_items_signature(after_items):
            continue
        structural_toolbar_paths.add(toolbar_path)
        if after_items is None:
            categories["toolbars"].append({"action": "remove_toolbar", "path": toolbar_path})
        else:
            categories["toolbars"].append({"action": "set_toolbar", "path": toolbar_path, "items": after_items})

    for key in sorted(set(default_params) | set(custom_params), key=lambda item: (item[0].lower(), item[1].lower())):
        # Children of structurally handled Custom_* toolbar groups are already
        # represented by set_toolbar/remove_toolbar and must not be duplicated.
        if key[0] in structural_toolbar_paths:
            continue
        before = default_params.get(key)
        after = custom_params.get(key)
        if before is not None and after is not None and before["type"] == after["type"] and before["value"] == after["value"]:
            continue

        representative = after or before
        if representative is None:
            continue
        category = _theme_ui_category(representative)
        if category is None:
            skipped_category, reason = _skipped_configuration_classification(representative)
            skipped_categories[skipped_category].append(
                _reviewable_skipped_instruction(before, after, skipped_category, reason)
            )
            continue

        if after is None:
            instruction = {"action": "remove", "path": before["path"], "name": before["name"]}
        else:
            instruction = {
                "action": "set", "path": after["path"], "name": after["name"],
                "type": after["type"], "value": after["value"],
            }
        categories[category].append(instruction)

    ui = {name: categories[name] for name in UI_CONFIGURATION_CATEGORIES if categories[name]}
    skipped = {name: skipped_categories[name] for name in skipped_order if skipped_categories[name]}
    retained_count = sum(len(items) for items in ui.values())
    skipped_count = sum(len(items) for items in skipped.values())

    accepted_data: dict[str, object] = {
        "schema": THEME_CONFIGURATION_SCHEMA,
        "version": THEME_CONFIGURATION_VERSION,
        "description": "UI-related FreeCAD configuration changes applied by External Theme Creator. The theme QSS is supplied separately and is not embedded here.",
        "output": {"filename": output_filename},
        "ui": ui,
        "generator_summary": {
            "included_ui_instructions": retained_count,
            "skipped_differences": skipped_count,
            "review_file": THEME_CONFIGURATION_SKIPPED_FILENAME,
        },
    }
    skipped_data: dict[str, object] = {
        "schema": "ui-launcher-theme-configuration-skipped",
        "version": 1,
        "description": "Review-only CFG differences rejected by the UI classifier. This file is not applied or exported with the theme.",
        "source": {
            "factory_default_cfg": str(default_cfg),
            "theme_cfg": str(custom_cfg),
        },
        "categories": skipped,
        "generator_summary": {
            "skipped_differences": skipped_count,
            "accepted_ui_instructions": retained_count,
        },
    }
    return accepted_data, skipped_data


class CFGInstructionsDialog(tk.Toplevel):
    def __init__(self, parent: "ThemeLauncherApp") -> None:
        super().__init__(parent)
        self.parent = parent
        self.title("CFG instructions")
        self.transient(parent)
        self.resizable(True, False)
        self.default_cfg_var = tk.StringVar(value="")
        self.custom_cfg_var = tk.StringVar(value="")
        self.output_filename_var = tk.StringVar(value="FreeCAD Theme.cfg")

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        ttk.Label(outer, text="Factory-default FreeCAD Configuration (.cfg)").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(outer, textvariable=self.default_cfg_var).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Button(outer, text="Browse", command=lambda: self._browse(self.default_cfg_var, "Select factory-default FreeCAD configuration")).grid(row=0, column=2, padx=(8, 0), pady=5)

        ttk.Label(outer, text="Theme Configuration (.cfg)").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(outer, textvariable=self.custom_cfg_var).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Button(outer, text="Browse", command=lambda: self._browse(self.custom_cfg_var, "Select theme configuration")).grid(row=1, column=2, padx=(8, 0), pady=5)

        ttk.Label(outer, text="Generated theme CFG filename").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(outer, textvariable=self.output_filename_var).grid(row=2, column=1, sticky="ew", pady=5)

        ttk.Button(outer, text="Generate CFG Instructions", command=self._generate).grid(row=3, column=0, columnspan=3, pady=(14, 0))
        self.geometry("820x190")
        self.minsize(700, 190)
        self.grab_set()

    def _browse(self, variable: tk.StringVar, title: str) -> None:
        current = variable.get().strip()
        initialdir = str(Path(current).expanduser().parent) if current else (self.parent.vars["theme_folder"].get().strip() or str(Path.home()))
        selected = filedialog.askopenfilename(title=title, initialdir=initialdir, filetypes=[("FreeCAD configuration", "*.cfg"), ("All files", "*.*")], parent=self)
        if selected:
            variable.set(selected)

    def _generate(self) -> None:
        try:
            default_cfg = Path(self.default_cfg_var.get().strip()).expanduser()
            custom_cfg = Path(self.custom_cfg_var.get().strip()).expanduser()
            if not default_cfg.is_file():
                raise LauncherError("Please select a valid factory-default FreeCAD configuration (.cfg).")
            if not custom_cfg.is_file():
                raise LauncherError("Please select a valid theme configuration (.cfg).")
            output_filename = self.output_filename_var.get().strip()
            if not output_filename or Path(output_filename).name != output_filename or Path(output_filename).suffix.lower() != ".cfg":
                raise LauncherError("Generated theme CFG filename must be a filename ending in .cfg, without a folder path.")
            data, skipped_data = _generate_theme_configuration(default_cfg, custom_cfg, output_filename)
            theme_folder_text = self.parent.vars["theme_folder"].get().strip()
            initialdir = theme_folder_text if theme_folder_text and Path(theme_folder_text).expanduser().is_dir() else str(custom_cfg.parent)
            output = filedialog.asksaveasfilename(
                title="Save CFG Instructions",
                initialdir=initialdir,
                initialfile=THEME_CONFIGURATION_FILENAME,
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                parent=self,
            )
            if not output:
                return
            output_path = Path(output)
            output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            skipped_path = output_path.parent / THEME_CONFIGURATION_SKIPPED_FILENAME
            skipped_path.write_text(json.dumps(skipped_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            count = sum(len(items) for items in data.get("ui", {}).values())
            skipped_count = sum(len(items) for items in skipped_data.get("categories", {}).values())
            messagebox.showinfo(
                APP_NAME,
                f"CFG Instructions generated.\n\nTheme instructions: {count}\nSkipped differences: {skipped_count}\n\n"
                f"{output_path.name}\n{skipped_path.name}\n\n"
                "Review the skipped file for settings that should be included in the theme.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)


def _default_freecad_user_cfg_path() -> Path:
    system = platform.system().lower()
    if system == "windows":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / "FreeCAD" / "user.cfg"
    if system == "darwin":
        return Path.home() / "Library" / "Preferences" / "FreeCAD" / "user.cfg"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "FreeCAD" / "user.cfg"
    return Path.home() / ".config" / "FreeCAD" / "user.cfg"


def _freecad_user_cfg_candidates(saved_path: str = "") -> list[Path]:
    """Return plausible existing FreeCAD user.cfg locations, including version-scoped dirs."""
    candidates: list[Path] = []

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            expanded = path.expanduser()
        except Exception:
            return
        key = os.path.normcase(os.path.abspath(str(expanded)))
        if all(os.path.normcase(os.path.abspath(str(existing))) != key for existing in candidates):
            candidates.append(expanded)

    def add_tree(root: Path | None) -> None:
        if root is None or not root.exists() or not root.is_dir():
            return
        add(root / "user.cfg")
        # FreeCAD 1.1+ and development builds may use version-scoped folders
        # such as FreeCAD/v1-1 or FreeCAD/v26-3. Keep this deliberately shallow.
        try:
            for child in root.iterdir():
                if child.is_dir():
                    add(child / "user.cfg")
        except OSError:
            pass

    if str(saved_path or "").strip():
        add(Path(str(saved_path).strip()))

    env_home = str(os.environ.get("FREECAD_USER_HOME", "") or "").strip()
    if env_home:
        add_tree(Path(env_home))

    add(_default_freecad_user_cfg_path())

    system = platform.system().lower()
    if system == "windows":
        roaming = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "FreeCAD"
        add_tree(roaming)
        local = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
        if local:
            add_tree(Path(local) / "FreeCAD")
    elif system == "darwin":
        add_tree(Path.home() / "Library" / "Preferences" / "FreeCAD")
        add_tree(Path.home() / ".config" / "FreeCAD")
    else:
        xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        add_tree(xdg / "FreeCAD")

    return candidates


def _load_theme_configuration(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LauncherError(f"Could not read {THEME_CONFIGURATION_FILENAME}: {exc}") from exc
    if data.get("schema") != THEME_CONFIGURATION_SCHEMA or data.get("version") not in (1, 2, THEME_CONFIGURATION_VERSION):
        raise LauncherError(f"Unsupported {THEME_CONFIGURATION_FILENAME} schema or version.")
    output = data.get("output")
    if not isinstance(output, dict):
        raise LauncherError(f"{THEME_CONFIGURATION_FILENAME} is missing output settings.")
    filename = str(output.get("filename", "") or "").strip()
    if not filename or Path(filename).name != filename or Path(filename).suffix.lower() != ".cfg":
        raise LauncherError(f"{THEME_CONFIGURATION_FILENAME} contains an unsafe or invalid output filename.")
    if data.get("version") == 1:
        if not isinstance(data.get("instructions"), list):
            raise LauncherError(f"{THEME_CONFIGURATION_FILENAME} instructions must be a list.")
    else:
        ui = data.get("ui")
        if not isinstance(ui, dict):
            raise LauncherError(f"{THEME_CONFIGURATION_FILENAME} is missing categorized UI instructions.")
        for category, instructions in ui.items():
            if category not in UI_CONFIGURATION_CATEGORIES or not isinstance(instructions, list):
                raise LauncherError(f"{THEME_CONFIGURATION_FILENAME} contains an invalid UI instruction category.")
    return data


def _iter_theme_configuration_instructions(data: dict[str, object]):
    if data.get("version") == 1:
        yield from data.get("instructions", [])
        return
    ui = data.get("ui", {})
    for category in UI_CONFIGURATION_CATEGORIES:
        for instruction in ui.get(category, []):
            yield instruction


def _apply_theme_configuration(source_cfg: Path, destination_cfg: Path, data: dict[str, object]) -> None:
    tree, root = _parse_cfg_xml_permissive(source_cfg)
    for index, instruction in enumerate(_iter_theme_configuration_instructions(data), start=1):
        if not isinstance(instruction, dict):
            raise LauncherError(f"Configuration instruction {index} is invalid.")
        action = str(instruction.get("action", "") or "").strip().lower()
        path = str(instruction.get("path", "") or "").strip()
        parts = [part for part in path.split("/") if part]

        # Runtime-only semantic UI actions do not map to FreeCAD CFG XML.
        # They are applied after the main window exists by the startup layout macro.
        if action == "tabify_docks":
            continue

        if action in {"set_toolbar", "remove_toolbar"}:
            if not parts:
                raise LauncherError(f"Configuration instruction {index} has no toolbar path.")
            toolbar_name = parts[-1]
            parent = ConfigXML._ensure_path(root, parts[:-1])
            existing = None
            existing_index = None
            for child_index, child in enumerate(list(parent)):
                if child.tag == "FCParamGroup" and child.attrib.get("Name") == toolbar_name:
                    existing = child
                    existing_index = child_index
                    break
            if existing is not None:
                parent.remove(existing)
            if action == "remove_toolbar":
                continue
            items = instruction.get("items")
            if not isinstance(items, list):
                raise LauncherError(f"Configuration instruction {index} toolbar items must be a list.")
            toolbar = ET.Element("FCParamGroup", {"Name": toolbar_name})
            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    raise LauncherError(f"Configuration instruction {index} toolbar item {item_index} is invalid.")
                item_name = str(item.get("name", "") or "").strip()
                tag = str(item.get("type", "") or "").strip()
                if not item_name or not tag.startswith("FC") or not tag.replace("_", "").isalnum():
                    raise LauncherError(f"Configuration instruction {index} toolbar item {item_index} is invalid.")
                value = str(item.get("value", "") or "")
                if tag == "FCText":
                    node = ET.SubElement(toolbar, tag, {"Name": item_name})
                    node.text = value
                else:
                    ET.SubElement(toolbar, tag, {"Name": item_name, "Value": value})
            if existing_index is None:
                parent.append(toolbar)
            else:
                parent.insert(existing_index, toolbar)
            continue

        name = str(instruction.get("name", "") or "").strip()
        if not name:
            raise LauncherError(f"Configuration instruction {index} has no parameter name.")
        group = ConfigXML._ensure_path(root, parts)
        if action == "remove":
            ConfigXML._remove_param(group, name)
            continue
        if action != "set":
            raise LauncherError(f"Configuration instruction {index} has unsupported action: {action}")
        tag = str(instruction.get("type", "") or "").strip()
        if not tag.startswith("FC") or not tag.replace("_", "").isalnum():
            raise LauncherError(f"Configuration instruction {index} has an invalid parameter type.")
        value = str(instruction.get("value", "") or "")
        ConfigXML._remove_param(group, name)
        if tag == "FCText":
            node = ET.SubElement(group, tag, {"Name": name})
            node.text = value
        else:
            ET.SubElement(group, tag, {"Name": name, "Value": value})
    destination_cfg.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination_cfg, encoding="utf-8", xml_declaration=True)


class ConfigXML:
    @staticmethod
    def _ensure_path(root: ET.Element, path_parts: list[str]) -> ET.Element:
        node = root
        for part in path_parts:
            found = None
            for child in node:
                if child.tag == "FCParamGroup" and child.attrib.get("Name") == part:
                    found = child
                    break
            if found is None:
                found = ET.SubElement(node, "FCParamGroup", {"Name": part})
            node = found
        return node

    @staticmethod
    def _set_string_param(group: ET.Element, name: str, value: str) -> None:
        for child in group:
            if child.attrib.get("Name") == name and child.tag in ("FCString", "FCText"):
                if child.tag == "FCText":
                    child.text = value
                    child.attrib.pop("Value", None)
                else:
                    child.attrib["Value"] = value
                return
        ET.SubElement(group, "FCString", {"Name": name, "Value": value})

    @staticmethod
    def _set_text_param(group: ET.Element, name: str, value: str) -> None:
        for child in group:
            if child.attrib.get("Name") == name and child.tag in ("FCText", "FCString"):
                if child.tag == "FCText":
                    child.text = value
                    child.attrib.pop("Value", None)
                else:
                    child.tag = "FCText"
                    child.attrib.pop("Value", None)
                    child.text = value
                return
        node = ET.SubElement(group, "FCText", {"Name": name})
        node.text = value

    @staticmethod
    def _remove_param(group: ET.Element, name: str) -> None:
        for child in list(group):
            if child.attrib.get("Name") == name:
                group.remove(child)

    @classmethod
    def write_runtime_user_cfg(
        cls,
        source_user_cfg: Path,
        destination_user_cfg: Path,
        stylesheet_text: str | None,
    ) -> None:
        if not source_user_cfg.exists():
            raise LauncherError(f"No .cfg file was found: {source_user_cfg}")

        tree, root = _parse_cfg_xml_permissive(source_user_cfg)

        group = cls._ensure_path(root, ["Preferences", "MainWindow"])
        if stylesheet_text:
            cls._set_text_param(group, "StyleSheet", stylesheet_text)
        cls._remove_param(group, "Theme")
        cls._remove_param(group, "ThemeStyleParametersFile")

        destination_user_cfg.parent.mkdir(parents=True, exist_ok=True)
        tree.write(destination_user_cfg, encoding="utf-8", xml_declaration=True)

    @classmethod
    def write_default_user_cfg(cls, destination_user_cfg: Path, stylesheet_text: str | None = None) -> None:
        root = ET.Element("FCParameters")
        group = cls._ensure_path(root, ["Preferences", "MainWindow"])
        if stylesheet_text:
            cls._set_text_param(group, "StyleSheet", stylesheet_text)
        destination_user_cfg.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(root).write(destination_user_cfg, encoding="utf-8", xml_declaration=True)




def _path_to_file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def _path_to_qss_local_path(path: Path) -> str:
    """Return a Qt stylesheet-friendly absolute local path.

    QSS image loading is more reliable with a quoted absolute filesystem path
    using forward slashes than with a percent-encoded file:// URI, especially
    on Windows when the theme folder contains spaces.
    """
    return str(path.resolve()).replace("\\", "/")




def _platform_shortcut_icon_suffix() -> str:
    system = platform.system().lower()
    if system == "windows":
        return ".ico"
    if system == "darwin":
        return ".icns"
    return ".png"


def _find_named_png(folder: Path, name_contains: str) -> Path | None:
    needle = name_contains.lower()
    matches = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".png" and needle in p.stem.lower()
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.name.lower())[0]


def _find_linux_shortcut_icon_in_folder(folder: Path) -> Path | None:
    entries = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".png"
    ]
    if not entries:
        return None

    by_name = {p.name.lower(): p for p in entries}
    for preferred_name in ("custom_icon.png", "shortcut.png"):
        match = by_name.get(preferred_name)
        if match is not None:
            return match

    for needle in ("custom_icon", "shortcut", "icon"):
        matches = [p for p in entries if needle in p.stem.lower()]
        if matches:
            return sorted(matches, key=lambda p: p.name.lower())[0]

    return sorted(entries, key=lambda p: p.name.lower())[0]


def _find_platform_shortcut_icon_in_folder(folder: Path) -> Path | None:
    system = platform.system().lower()
    if system == "linux":
        candidate = folder / "Custom_Icon.png"
        return candidate if candidate.is_file() else None
    wanted = _platform_shortcut_icon_suffix()
    candidate = folder / ("Custom_Icon" + wanted)
    if candidate.is_file():
        return candidate
    matches = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == wanted
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.name.lower())[0]




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


def _find_freecad_python(freecad_exe: Path) -> Path | None:
    """Find a Python interpreter associated with the selected FreeCAD install."""
    folder = Path(freecad_exe).resolve().parent
    names = ('pythonw.exe', 'python.exe') if os.name == 'nt' else ('python3', 'python')
    roots = [folder, folder / 'bin', folder.parent, folder.parent / 'bin',
             folder.parent / 'Library' / 'bin', folder.parent.parent / 'bin']
    if platform.system().lower() == 'darwin':
        for ancestor in (folder, *folder.parents):
            if ancestor.name == 'Contents' and ancestor.parent.suffix.lower() == '.app':
                roots.insert(0, ancestor / 'Resources' / 'bin')
                break
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
        'plugins/platforms',
        'lib/python3.13/site-packages/PySide6/Qt/plugins/platforms',
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
            if (location / ('qwindows.dll' if os.name == 'nt' else 'libqcocoa.dylib' if sys.platform == 'darwin' else 'libqxcb.so')).is_file():
                return location
    return None


def _splash_diagnostic(runtime_root: Path, message: str) -> None:
    if not any(token in str(message).upper() for token in ('FALLBACK', 'ERROR', 'FAILED')):
        return
    try:
        from datetime import datetime
        runtime_root.mkdir(parents=True, exist_ok=True)
        with (runtime_root / 'splash-startup.log').open('a', encoding='utf-8') as out:
            out.write(datetime.now().isoformat(timespec='seconds') + ' ' + message + '\n')
    except Exception:
        pass


def _start_native_pixel_splash(freecad_exe, image_path, runtime_root):
    from ExternalThemeCreatorSplashControl import _start_native_pixel_splash as start
    return start(freecad_exe, image_path, runtime_root)


def _stop_native_pixel_splash(handle):
    from ExternalThemeCreatorSplashControl import _stop_native_pixel_splash as stop
    return stop(handle)


def _find_theme_splash_png(folder: Path) -> Path | None:
    return (folder / "splash" / "freecadsplash.png") if (folder / "splash" / "freecadsplash.png").is_file() else None


def _prepare_native_splash_asset(source: Path, runtime_root: Path) -> tuple[Path, str]:
    """Use the theme PNG exactly as supplied, without scaling or resampling."""
    source = Path(source).resolve()

    # v0.9.12 generated an interpolated @2x runtime copy. Remove those old
    # helper artifacts when present so the runtime folder accurately reflects
    # the current 1:1 splash policy. They are not needed for launching.
    old_output_dir = runtime_root / "splash"
    for old_name in ("theme_splash@2x.png", "prepare_hidpi_splash.py"):
        try:
            old_path = old_output_dir / old_name
            if old_path.is_file():
                old_path.unlink()
        except Exception:
            pass
    try:
        if old_output_dir.is_dir() and not any(old_output_dir.iterdir()):
            old_output_dir.rmdir()
    except Exception:
        pass

    if not source.is_file():
        raise RuntimeError(f"Splash PNG does not exist: {source}")

    return source, "original PNG passed through unchanged (1:1 source pixels; no scaling or resampling)"

def _desktop_file_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _rewrite_qss_urls(qss_text: str, base_folder: Path) -> str:
    pattern = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)

    def repl(match: re.Match[str]) -> str:
        raw_target = match.group(2).strip()
        if not raw_target:
            return match.group(0)
        lower = raw_target.lower()
        if lower.startswith(("file:", "qrc:", ":", "http://", "https://", "data:")):
            return match.group(0)
        candidate = (base_folder / raw_target).resolve()
        if not candidate.exists():
            return match.group(0)
        return f'url("{_path_to_qss_local_path(candidate)}")'

    return pattern.sub(repl, qss_text)


def _build_runtime_stylesheet(qss_path: Path) -> str:
    try:
        raw = qss_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = qss_path.read_text(encoding="utf-8-sig")
    return _rewrite_qss_urls(raw, qss_path.parent)


def _theme_runtime_layout_instructions(theme_folder: Path) -> list[dict[str, object]]:
    """Return runtime-only semantic layout instructions from theme-configuration.json."""
    config_path = theme_folder / THEME_CONFIGURATION_FILENAME
    if not config_path.is_file():
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    ui = data.get("ui", {}) if isinstance(data, dict) else {}
    layout = ui.get("layout", []) if isinstance(ui, dict) else []
    if not isinstance(layout, list):
        return []
    return [
        item for item in layout
        if isinstance(item, dict) and str(item.get("action", "")).strip().lower() == "tabify_docks"
    ]


def _make_startup_layout_script(script_path: Path, instructions: list[dict[str, object]]) -> Path:
    """Create a FreeCAD startup macro for portable semantic dock-layout actions."""
    script_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(instructions, ensure_ascii=False)
    script_text = f'''from __future__ import annotations
import json
try:
    from PySide import QtCore, QtGui
    try:
        from PySide import QtWidgets
    except Exception:
        QtWidgets = QtGui
except Exception:
    from PySide6 import QtCore, QtGui, QtWidgets
import FreeCAD as App
import FreeCADGui as Gui
ACTIONS = json.loads({payload!r})

def _spec_names(spec):
    names = []
    if isinstance(spec, str):
        if spec.strip(): names.append(spec.strip())
    elif isinstance(spec, dict):
        for key in ("object_name", "fallback_title", "title", "name"):
            value = str(spec.get(key, "") or "").strip()
            if value and value not in names: names.append(value)
    return names

def _find_dock(mw, spec):
    names = _spec_names(spec)
    if not names: return None
    try:
        docks = mw.findChildren(QtWidgets.QDockWidget)
    except Exception:
        docks = []
    for wanted in names:
        for dock in docks:
            try:
                if str(dock.objectName()) == wanted:
                    return dock
            except Exception:
                pass
    for wanted in names:
        for dock in docks:
            try:
                if str(dock.windowTitle()) == wanted:
                    return dock
            except Exception:
                pass
    lowered = {{name.casefold() for name in names}}
    for dock in docks:
        try:
            if str(dock.objectName()).casefold() in lowered or str(dock.windowTitle()).casefold() in lowered:
                return dock
        except Exception:
            pass
    return None

def _active_spec(action):
    active = action.get("active", "")
    if isinstance(active, str):
        key = active.strip().casefold()
        if key == "primary": return action.get("primary")
        if key == "secondary": return action.get("secondary")
    return active

def _apply_layout():
    try:
        mw = Gui.getMainWindow()
    except Exception:
        return False
    if mw is None:
        return False
    ok = True
    for action in ACTIONS:
        if str(action.get("action", "")).strip().lower() != "tabify_docks":
            continue
        primary = _find_dock(mw, action.get("primary"))
        secondary = _find_dock(mw, action.get("secondary"))
        if primary is None or secondary is None or primary is secondary:
            ok = False
            continue
        try:
            primary.show()
            secondary.show()
            mw.tabifyDockWidget(primary, secondary)
            active = _find_dock(mw, _active_spec(action))
            if active is None:
                active = primary
            active.show()
            active.raise_()
        except Exception as exc:
            ok = False
            try:
                App.Console.PrintError("External Theme Creator: tabify_docks failed: " + str(exc) + "\\n")
            except Exception:
                pass
    return ok

for delay in (0, 250, 750, 1500, 3000):
    QtCore.QTimer.singleShot(delay, _apply_layout)
'''
    script_path.write_text(script_text, encoding="utf-8")
    return script_path


def _make_startup_stylesheet_script(script_path: Path, qss_text: str, qss_path: Path) -> Path:
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_text = f"""from __future__ import annotations
try:
    from PySide import QtCore, QtGui
    try:
        from PySide import QtWidgets
    except Exception:
        QtWidgets = QtGui
except Exception:
    from PySide6 import QtCore, QtGui, QtWidgets
import FreeCAD as App
import FreeCADGui as Gui
QSS_TEXT = {qss_text!r}
QSS_PATH = {str(qss_path.resolve())!r}

# Explicit handoff for the QSS Reload development workbench.
# This stores the original editable QSS path, not the generated runtime macro.
App.ParamGet("User parameter:BaseApp/Preferences/ExternalThemeCreator").SetString(
    "CreatorQSSPath", QSS_PATH
)

def _capture_toolbar_sizes(mw):
    saved_main = None
    try:
        size = mw.iconSize()
        saved_main = (size.width(), size.height())
    except Exception:
        saved_main = None
    saved_toolbars = []
    try:
        toolbars = mw.findChildren(QtWidgets.QToolBar)
    except Exception:
        toolbars = []
    for tb in toolbars:
        try:
            size = tb.iconSize()
            saved_toolbars.append((tb, size.width(), size.height()))
        except Exception:
            pass
    return saved_main, saved_toolbars

def _restore_toolbar_sizes(mw, saved_main, saved_toolbars):
    try:
        if saved_main and saved_main[0] > 0 and saved_main[1] > 0:
            mw.setIconSize(QtCore.QSize(saved_main[0], saved_main[1]))
    except Exception:
        pass
    for tb, width, height in saved_toolbars:
        try:
            if width > 0 and height > 0:
                tb.setIconSize(QtCore.QSize(width, height))
        except Exception:
            pass

def _apply_stylesheet() -> None:
    try:
        mw = Gui.getMainWindow()
    except Exception:
        QtCore.QTimer.singleShot(250, _apply_stylesheet)
        return
    if mw is None:
        QtCore.QTimer.singleShot(250, _apply_stylesheet)
        return
    try:
        saved_main, saved_toolbars = _capture_toolbar_sizes(mw)
        app = QtWidgets.QApplication.instance()
        if app is None:
            QtCore.QTimer.singleShot(250, _apply_stylesheet)
            return
        # Clear any legacy main-window-local stylesheet first, then apply the
        # theme globally so dynamically-created popup widgets inherit it too.
        mw.setStyleSheet("")
        app.setStyleSheet("")
        app.setStyleSheet(QSS_TEXT)
        _restore_toolbar_sizes(mw, saved_main, saved_toolbars)
        QtCore.QTimer.singleShot(0, lambda: _restore_toolbar_sizes(mw, saved_main, saved_toolbars))
        QtCore.QTimer.singleShot(200, lambda: _restore_toolbar_sizes(mw, saved_main, saved_toolbars))
        QtCore.QTimer.singleShot(500, lambda: _restore_toolbar_sizes(mw, saved_main, saved_toolbars))
        Gui.updateGui()
    except Exception:
        QtCore.QTimer.singleShot(250, _apply_stylesheet)

QtCore.QTimer.singleShot(0, _apply_stylesheet)
"""
    script_path.write_text(script_text, encoding="utf-8")
    return script_path


def _make_packaged_theme_scripts_startup(script_path: Path, theme_folder: Path) -> Path:
    """Load a signed package's optional scripts in the newly started FreeCAD GUI.

    Develop-theme script startup is provided by ExternalThemeCreatorRuntime.
    Packaged themes launch through this engine on every OS (including direct
    AppImage restart and prepared shortcuts), so install their scripts here.
    """
    script_path.parent.mkdir(parents=True, exist_ok=True)
    # This is the installed workbench's own ThemeScriptManager, not a module
    # imported from the theme package or a temporary AppImage mount location.
    manager_directory = Path(__file__).resolve().parent
    macro_text = f"""from __future__ import annotations
import sys
try:
    from PySide import QtCore
except ImportError:
    from PySide6 import QtCore
import FreeCAD as App
import FreeCADGui as Gui
THEME_FOLDER = {str(theme_folder.resolve())!r}
MANAGER_DIRECTORY = {str(manager_directory)!r}

def _start_packaged_theme_scripts(retries=0):
    try:
        if Gui.getMainWindow() is None:
            if retries < 40:
                QtCore.QTimer.singleShot(250, lambda: _start_packaged_theme_scripts(retries + 1))
            else:
                App.Console.PrintError("External Theme Creator: theme script startup timed out waiting for FreeCAD GUI.\\n")
            return
        if MANAGER_DIRECTORY not in sys.path:
            sys.path.insert(0, MANAGER_DIRECTORY)
        import ThemeScriptManager as TSM
        TSM.install_from_folder(THEME_FOLDER)
    except Exception:
        import traceback
        App.Console.PrintError("External Theme Creator: packaged theme scripts failed to load:\\n" + traceback.format_exc())

QtCore.QTimer.singleShot(500, _start_packaged_theme_scripts)
"""
    script_path.write_text(macro_text, encoding="utf-8")
    return script_path



class FreeCADLocator:
    @staticmethod
    def candidate_paths() -> list[Path]:
        system = platform.system().lower()
        candidates: list[Path] = []

        if system == "windows":
            env_vars = [
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            relative_paths = [
                Path("FreeCAD 1.1/bin/FreeCAD.exe"),
                Path("FreeCAD 1.0/bin/FreeCAD.exe"),
                Path("FreeCAD/bin/FreeCAD.exe"),
                Path("FreeCAD*/bin/FreeCAD.exe"),
            ]
            for base in env_vars:
                if not base:
                    continue
                base_path = Path(base)
                for rel in relative_paths:
                    if "*" in str(rel):
                        candidates.extend(base_path.glob(str(rel)))
                    else:
                        candidates.append(base_path / rel)
            for exe_name in ["FreeCAD.exe", "freecad.exe"]:
                found = shutil.which(exe_name)
                if found:
                    candidates.append(Path(found))

        elif system == "darwin":
            candidates.extend(
                [
                    Path("/Applications/FreeCAD.app/Contents/MacOS/FreeCAD"),
                    Path.home() / "Applications/FreeCAD.app/Contents/MacOS/FreeCAD",
                ]
            )
            for exe_name in ["FreeCAD", "freecad"]:
                found = shutil.which(exe_name)
                if found:
                    candidates.append(Path(found))

        else:
            candidates.extend(
                [
                    Path("/usr/bin/freecad"),
                    Path("/usr/local/bin/freecad"),
                    Path("/snap/bin/freecad"),
                    Path("/var/lib/flatpak/exports/bin/org.freecad.FreeCAD"),
                    Path.home() / ".local/bin/freecad",
                ]
            )
            for exe_name in ["freecad", "FreeCAD", "org.freecad.FreeCAD"]:
                found = shutil.which(exe_name)
                if found:
                    candidates.append(Path(found))

        unique: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            path_str = str(path)
            if path_str not in seen:
                seen.add(path_str)
                unique.append(path)
        return unique

    @classmethod
    def first_existing_candidate(cls) -> str:
        for path in cls.candidate_paths():
            if path.exists():
                return str(path)
        return ""


class ThemeFolderScanner:
    @staticmethod
    def find_first_file(folder: Path, suffix: str) -> Path | None:
        matches = sorted(
            [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == suffix.lower()],
            key=lambda p: p.name.lower(),
        )
        return matches[0] if matches else None

    @classmethod
    def find_cfg(cls, folder: Path) -> Path | None:
        preferred_names = ["user.cfg", "theme.cfg", "profile.cfg"]
        for name in preferred_names:
            candidate = folder / name
            if candidate.exists() and candidate.is_file():
                return candidate
        return cls.find_first_file(folder, ".cfg")

    @classmethod
    def find_qss(cls, folder: Path) -> Path | None:
        preferred_names = ["theme.qss", "style.qss", "stylesheet.qss"]
        for name in preferred_names:
            candidate = folder / name
            if candidate.exists() and candidate.is_file():
                return candidate
        return cls.find_first_file(folder, ".qss")

    @classmethod
    def find_splash(cls, folder: Path) -> Path | None:
        candidate = folder / "splash" / "freecadsplash.png"
        return candidate if candidate.is_file() else None

    @classmethod
    def find_external_icon_theme_root(cls, folder: Path) -> Path | None:
        preferred_names = ["icons", "Icons", "images", "Images"]
        for name in preferred_names:
            candidate = folder / name
            if candidate.exists() and candidate.is_dir() and cls.folder_contains_supported_icons(candidate):
                return candidate

        if cls.folder_contains_supported_icons(folder):
            return folder

        return None

    @staticmethod
    def folder_contains_supported_icons(folder: Path) -> bool:
        try:
            for child in folder.iterdir():
                if child.is_file() and child.suffix.lower() in SUPPORTED_ICON_EXTENSIONS:
                    return True
        except Exception:
            return False
        return False



class ExportThemeDialog(tk.Toplevel):
    def __init__(self, master: "ThemeLauncherApp", scan: dict[str, object]) -> None:
        super().__init__(master)
        self.master = master
        self.scan = scan
        self.title("Export Theme")
        self.transient(master)
        self.grab_set()
        self.resizable(True, True)
        self.minsize(860, 600)
        self.result: dict[str, str] | None = None
        self.vars: dict[str, object] = {
            "theme_package": tk.StringVar(value=THEME_PACKAGE_OPTION_COMPLETE),
            "require_external_qss": tk.BooleanVar(value=False),
            "external_qss_url": tk.StringVar(value=""),
        }
        self._suppress_license_choice_events = False
        self._scroll_canvas: tk.Canvas | None = None
        self._scroll_inner: ttk.Frame | None = None
        self._scroll_window_id: int | None = None
        self._build_ui()
        self._populate_from_settings()
        self._refresh_summary()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        default_width = max(860, self.winfo_reqwidth())
        self.geometry(f"{default_width}x900")

    def _build_ui(self) -> None:
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)

        self._scroll_canvas = tk.Canvas(shell, highlightthickness=0)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        vscroll = ttk.Scrollbar(shell, orient="vertical", command=self._scroll_canvas.yview)
        vscroll.pack(side="right", fill="y")
        self._scroll_canvas.configure(yscrollcommand=vscroll.set)

        outer = ttk.Frame(self._scroll_canvas, padding=12)
        self._scroll_inner = outer
        self._scroll_window_id = self._scroll_canvas.create_window((0, 0), window=outer, anchor="nw")

        outer.bind("<Configure>", self._on_export_dialog_content_configure)
        self._scroll_canvas.bind("<Configure>", self._on_export_dialog_canvas_configure)

        metadata = ttk.LabelFrame(outer, text="Theme Metadata", padding=10)
        metadata.pack(fill="x", pady=(12, 0))
        self._add_entry_row(metadata, 0, "Theme Name", "theme_name")
        self._add_readonly_row(metadata, 1, "Theme ID", "theme_id")
        self._add_entry_row(metadata, 2, "Theme Version", "theme_version")
        self._add_entry_row(metadata, 3, "Author Name", "author_name")
        self._add_entry_row(metadata, 4, "FreeCAD Version Tested", "freecad_version_tested")
        self._add_path_row(metadata, 5, "Author Key", "author_key_file", self._browse_author_key, "Create Author Key", self._create_author_key)
        self._add_text_row(metadata, 6, "Description", "description", 4)
        self._add_text_row(metadata, 7, "Copyright", "copyright", 3)
        self._add_license_dropdown_row(metadata, 8, "License", "license")
        self._add_text_row(metadata, 9, "License Brief", "license_terms", 4)

        package = ttk.LabelFrame(outer, text="Auto-generated Package Info", padding=10)
        package.pack(fill="x", pady=(12, 0))
        self._add_readonly_row(package, 0, "Schema Version", "schema_version")
        self._add_readonly_row(package, 1, "Package Type", "package_type")
        self._add_readonly_row(package, 2, "Launcher Version", "launcher_version")
        self._add_readonly_row(package, 3, "Payload Encryption", "payload_encryption")
        self._add_readonly_row(package, 4, "Key Fingerprint", "key_fingerprint")

        summary = ttk.LabelFrame(outer, text="Theme Folder Summary", padding=10)
        summary.pack(fill="both", expand=True, pady=(12, 0))
        summary.columnconfigure(1, weight=1)
        self._add_readonly_row(summary, 0, "Theme Folder", "theme_folder")
        self._add_readonly_row(summary, 1, "SVG count", "svg_count")
        self._add_readonly_row(summary, 2, "PNG count", "png_count")
        self._add_readonly_row(summary, 3, "QSS count", "qss_count")
        self._add_readonly_row(summary, 4, "Total included files", "total_files")

        ttk.Label(summary, text="Included files").grid(row=5, column=0, sticky="nw", padx=(0, 10), pady=(6, 4))
        files_frame = ttk.Frame(summary)
        files_frame.grid(row=5, column=1, columnspan=3, sticky="nsew", pady=(6, 4))
        summary.rowconfigure(5, weight=1)
        files_frame.rowconfigure(0, weight=1)
        files_frame.columnconfigure(0, weight=1)
        self.included_files = tk.Text(files_frame, height=10, wrap="none")
        self.included_files.grid(row=0, column=0, sticky="nsew")
        files_scroll = ttk.Scrollbar(files_frame, orient="vertical", command=self.included_files.yview)
        files_scroll.grid(row=0, column=1, sticky="ns")
        self.included_files.configure(yscrollcommand=files_scroll.set, state="disabled")

        ttk.Label(summary, text="Validation").grid(row=8, column=0, sticky="nw", padx=(0, 10), pady=(6, 4))
        validation_frame = ttk.Frame(summary)
        validation_frame.grid(row=8, column=1, columnspan=3, sticky="nsew", pady=(6, 4))
        validation_frame.rowconfigure(0, weight=1)
        validation_frame.columnconfigure(0, weight=1)
        self.validation_text = tk.Text(validation_frame, height=6, wrap="word")
        self.validation_text.grid(row=0, column=0, sticky="nsew")
        validation_scroll = ttk.Scrollbar(validation_frame, orient="vertical", command=self.validation_text.yview)
        validation_scroll.grid(row=0, column=1, sticky="ns")
        self.validation_text.configure(yscrollcommand=validation_scroll.set, state="disabled")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="Validate", command=self._refresh_summary).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Export", command=self._export_clicked).pack(side="right", padx=(0, 8))

        self._bind_export_dialog_mousewheel_recursive(self)
        self._on_export_dialog_content_configure()

    def _on_export_dialog_content_configure(self, _event=None) -> None:
        if self._scroll_canvas is None:
            return
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _on_export_dialog_canvas_configure(self, event) -> None:
        if self._scroll_canvas is None or self._scroll_window_id is None:
            return
        self._scroll_canvas.itemconfigure(self._scroll_window_id, width=event.width)

    def _on_export_dialog_mousewheel(self, event) -> str | None:
        if self._scroll_canvas is None:
            return None
        delta = getattr(event, "delta", 0)
        if delta:
            step = -1 if delta > 0 else 1
            self._scroll_canvas.yview_scroll(step, "units")
            return "break"
        num = getattr(event, "num", None)
        if num == 4:
            self._scroll_canvas.yview_scroll(-1, "units")
            return "break"
        if num == 5:
            self._scroll_canvas.yview_scroll(1, "units")
            return "break"
        return None

    def _bind_export_dialog_mousewheel_recursive(self, widget) -> None:
        widget.bind("<MouseWheel>", self._on_export_dialog_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_export_dialog_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_export_dialog_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_export_dialog_mousewheel_recursive(child)

    def _add_entry_row(self, parent, row, label, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.vars[key] = tk.StringVar(value="")
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        entry.bind("<KeyRelease>", lambda _e: self._refresh_summary())
        parent.columnconfigure(1, weight=1)

    def _add_readonly_row(self, parent, row, label, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.vars[key] = tk.StringVar(value="")
        entry = ttk.Entry(parent, textvariable=self.vars[key], state="readonly")
        entry.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)

    def _add_path_row(self, parent, row, label, key, browse_command, extra_button_text, extra_button_command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.vars[key] = tk.StringVar(value="")
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        entry.bind("<KeyRelease>", lambda _e: self._refresh_summary())
        ttk.Button(parent, text="Browse", command=browse_command).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=4)
        ttk.Button(parent, text=extra_button_text, command=extra_button_command).grid(row=row, column=3, sticky="ew", padx=(8, 0), pady=4)
        parent.columnconfigure(1, weight=1)

    def _add_license_dropdown_row(self, parent, row, label, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        options = _license_options_for_dir(self.master.base_dir)
        self.vars[key] = tk.StringVar(value=options[0] if options else CUSTOM_LICENSE_OPTION)
        combo = ttk.Combobox(parent, textvariable=self.vars[key], values=options, state="readonly")
        combo.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        combo.bind("<<ComboboxSelected>>", self._on_license_choice_changed)
        parent.columnconfigure(1, weight=1)

    def _add_theme_package_dropdown_row(self, parent, row, label, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        options = [THEME_PACKAGE_OPTION_COMPLETE, THEME_PACKAGE_OPTION_ARTWORK_ONLY]
        self.vars[key] = tk.StringVar(value=THEME_PACKAGE_OPTION_COMPLETE)
        combo = ttk.Combobox(parent, textvariable=self.vars[key], values=options, state="readonly")
        combo.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        combo.bind("<<ComboboxSelected>>", self._on_theme_package_changed)
        parent.columnconfigure(1, weight=1)

    def _add_checkbox_with_url_row(self, parent, row, label, key, url_key):
        if not hasattr(self, "_distribution_rows"):
            self._distribution_rows = {}
        self.vars[key] = tk.BooleanVar(value=False)
        check = ttk.Checkbutton(parent, text=label, variable=self.vars[key], command=self._on_distribution_asset_toggle)
        check.grid(row=row, column=0, columnspan=4, sticky="w", pady=(4, 2))
        self.vars[url_key] = tk.StringVar(value="")
        url_label = ttk.Label(parent, text="Web Address")
        url_label.grid(row=row + 1, column=0, sticky="w", padx=(18, 10), pady=(2, 4))
        url_entry = ttk.Entry(parent, textvariable=self.vars[url_key])
        url_entry.grid(row=row + 1, column=1, columnspan=3, sticky="ew", pady=(2, 4))
        url_entry.bind("<KeyRelease>", lambda _e: self._refresh_summary())
        self._distribution_rows[key] = {
            "check": check,
            "url_label": url_label,
            "url_entry": url_entry,
        }

    def _add_text_row(self, parent, row, label, key, height):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=(6, 4))
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, columnspan=3, sticky="nsew", pady=(6, 4))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        widget = tk.Text(frame, height=height, wrap="word")
        widget.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        widget.configure(yscrollcommand=scroll.set)
        widget.bind("<KeyRelease>", lambda _e: self._refresh_summary())
        self.vars[key] = widget
        parent.columnconfigure(1, weight=1)

    def _set_text_widget(self, key, value):
        widget = self.vars[key]
        widget.delete("1.0", "end")
        widget.insert("1.0", value)

    def _get_text_widget(self, key):
        return self.vars[key].get("1.0", "end").strip()

    def _current_theme_folder_path(self) -> Path:
        return Path(str(self.scan.get("theme_folder", "") or "")).expanduser()

    def _apply_license_choice_defaults(self, license_choice: str) -> None:
        if license_choice == CUSTOM_LICENSE_OPTION:
            brief_path = self._current_theme_folder_path() / CUSTOM_LICENSE_BRIEF_RELPATH
            self._set_text_widget("license_terms", brief_path.read_text(encoding="utf-8-sig").strip() if brief_path.is_file() else "")
            return
        self._set_text_widget("license_terms", _default_license_brief_for_choice(license_choice))

    def _on_license_choice_changed(self, _event=None) -> None:
        if self._suppress_license_choice_events:
            return
        license_choice = self.vars["license"].get().strip()
        self._apply_license_choice_defaults(license_choice)
        self._refresh_summary()

    def _sync_distribution_ui_visibility(self) -> None:
        return

    def _on_theme_package_changed(self, _event=None) -> None:
        self._refresh_summary()

    def _on_distribution_asset_toggle(self) -> None:
        self._refresh_summary()

    def _populate_from_settings(self):
        s = self.master.settings
        self.vars["theme_name"].set(s.export_theme_name)
        self.vars["theme_version"].set(s.export_theme_version)
        self.vars["author_name"].set(s.export_author_name)
        self.vars["freecad_version_tested"].set(s.export_freecad_version_tested)
        self.vars["author_key_file"].set(s.author_key_file)
        self._set_text_widget("description", s.export_description)
        self._set_text_widget("copyright", s.export_copyright)
        self.vars["theme_package"].set(THEME_PACKAGE_OPTION_COMPLETE)
        self.vars["require_external_qss"].set(False)
        self.vars["external_qss_url"].set("")
        self._suppress_license_choice_events = True
        license_options = _license_options_for_dir(self.master.base_dir)
        saved_license = str(getattr(s, "export_license", CUSTOM_LICENSE_OPTION) or CUSTOM_LICENSE_OPTION)
        if saved_license not in license_options:
            saved_license = CUSTOM_LICENSE_OPTION
        self.vars["license"].set(saved_license)
        self._suppress_license_choice_events = False
        license_brief = str(getattr(s, "export_license_terms", "") or "")
        if saved_license == CUSTOM_LICENSE_OPTION:
            brief_path = self._current_theme_folder_path() / CUSTOM_LICENSE_BRIEF_RELPATH
            if brief_path.is_file(): license_brief = _read_text(brief_path).strip()
        elif not license_brief:
            license_brief = _default_license_brief_for_choice(saved_license)
        self._set_text_widget("license_terms", license_brief)

        self._sync_distribution_ui_visibility()
        self.vars["schema_version"].set(THEME_SCHEMA_VERSION)
        self.vars["package_type"].set(THEME_PACKAGE_TYPE)
        self.vars["launcher_version"].set(APP_VERSION)
        self.vars["payload_encryption"].set(THEME_PAYLOAD_ENCRYPTION)
        self.vars["theme_folder"].set(str(self.scan.get("theme_folder", "")))

    def _browse_author_key(self):
        current = self.vars["author_key_file"].get().strip()
        initialdir = str(Path(current).expanduser().parent) if current else str(Path.home())
        path = filedialog.askopenfilename(parent=self, title="Select Author Key", initialdir=initialdir, filetypes=[("PEM files", "*.pem"), ("All files", "*.*")])
        if path:
            self.vars["author_key_file"].set(path)
            self._refresh_summary()

    def _create_author_key(self):
        author_name = self.vars["author_name"].get().strip()
        if not author_name:
            messagebox.showerror(APP_NAME, "Author Name is required before creating an Author Key.", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title="Create Author Key", defaultextension=".pem", initialfile=f"{_slugify_theme_id(author_name) or 'author'}_private.pem", filetypes=[("PEM files", "*.pem"), ("All files", "*.*")])
        if not path:
            return
        try:
            Fernet, serialization, Ed25519PrivateKey, Ed25519PublicKey = _require_crypto()
            private_key = Ed25519PrivateKey.generate()
            private_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            public_bytes = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            private_path = Path(path)
            public_path = private_path.with_name(private_path.stem + ".public.pem")
            private_path.write_bytes(private_bytes)
            public_path.write_bytes(public_bytes)
            self.vars["author_key_file"].set(str(private_path))
            self._refresh_summary()
            messagebox.showinfo(APP_NAME, f"Author Key created:\n{private_path}\n\nPublic Key created:\n{public_path}", parent=self)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Unable to create Author Key:\n{exc}", parent=self)

    def _collect_values(self):
        values = {
            "theme_name": self.vars["theme_name"].get().strip(),
            "theme_version": self.vars["theme_version"].get().strip(),
            "author_name": self.vars["author_name"].get().strip(),
            "freecad_version_tested": self.vars["freecad_version_tested"].get().strip(),
            "author_key_file": self.vars["author_key_file"].get().strip(),
            "description": self._get_text_widget("description"),
            "copyright": self._get_text_widget("copyright"),
            "theme_package": THEME_PACKAGE_OPTION_COMPLETE,
            "require_external_qss": False,
            "external_qss_url": "",
            "license": self.vars["license"].get().strip(),
            "license_terms": self._get_text_widget("license_terms"),

        }
        values["theme_id"] = _slugify_theme_id(values["theme_name"])
        return values

    def _validate(self, values):
        errors = []
        theme_package = THEME_PACKAGE_OPTION_COMPLETE
        artwork_only = False
        if not values["theme_name"]:
            errors.append("Theme Name is required.")
        if not values["theme_id"]:
            errors.append("Theme ID could not be generated from Theme Name.")
        if not values["theme_version"]:
            errors.append("Theme Version is required.")
        if not values["author_name"]:
            errors.append("Author Name is required.")
        if not values["freecad_version_tested"]:
            errors.append("FreeCAD Version Tested is required.")
        if not values["description"]:
            errors.append("Description is required.")
        if not values["copyright"]:
            errors.append("Copyright is required.")
        if not values["license"]:
            errors.append("License is required.")
        if not values["license_terms"]:
            errors.append("License Brief is required.")
        if values.get("license") == CUSTOM_LICENSE_OPTION:
            theme_folder = self._current_theme_folder_path()
            custom_license_path = theme_folder / THEME_LICENSE_RELPATH
            if not custom_license_path.exists() or not custom_license_path.is_file():
                errors.append(f'Custom License requires "{THEME_LICENSE_RELPATH}" inside the Theme Folder.')
        elif values.get("license"):
            source_path = _license_source_path(self.master.base_dir, values["license"])
            if source_path is None or not source_path.exists() or not source_path.is_file():
                errors.append(f'Selected license file was not found in "{CC_LICENSES_DIR_NAME}".')
        if not values["author_key_file"]:
            errors.append("Author Key is required.")
        else:
            p = Path(values["author_key_file"]).expanduser()
            if not p.exists() or not p.is_file():
                errors.append("Author Key does not exist or is not a file.")
            else:
                try:
                    _, _, fp = _load_author_private_key(p)
                    self.vars["key_fingerprint"].set(fp)
                except Exception as exc:
                    errors.append(str(exc))
        included_files = self.scan.get("included_files", [])
        counts = self.scan.get("counts", {})
        effective_included_files = _effective_export_file_list(self.scan, self._current_theme_folder_path(), values.get("license", ""), theme_package)
        if not effective_included_files:
            errors.append("No exportable theme files were found in the Theme Folder.")
        if counts.get(".svg", 0) + counts.get(".png", 0) == 0:
            errors.append("The Theme Folder must contain at least one .svg or .png asset.")
        if not artwork_only:
            has_theme_configuration = bool(self.scan.get("detected_theme_configuration", ""))
            if not has_theme_configuration:
                errors.append(f'A Complete Theme requires a top-level "{THEME_CONFIGURATION_FILENAME}" file.')
        else:
            if values.get("require_external_qss"):
                qss_url = values.get("external_qss_url", "")
                if not qss_url:
                    errors.append("Web Address is required for external style-sheet (.qss).")
                else:
                    try:
                        _external_asset_filename_from_url(qss_url, ".qss")
                    except Exception as exc:
                        errors.append(str(exc))
        return errors

    def _refresh_summary(self):
        values = self._collect_values()
        self.vars["theme_id"].set(values["theme_id"])
        counts = self.scan.get("counts", {})
        self.vars["svg_count"].set(str(counts.get(".svg", 0)))
        self.vars["png_count"].set(str(counts.get(".png", 0)))
        self.vars["qss_count"].set(str(counts.get(".qss", 0)))
        effective_included_files = _effective_export_file_list(self.scan, self._current_theme_folder_path(), values.get("license", ""), values.get("theme_package", THEME_PACKAGE_OPTION_COMPLETE))
        self.vars["total_files"].set(str(len(effective_included_files)))
        if not values["author_key_file"]:
            self.vars["key_fingerprint"].set("")
        self.included_files.configure(state="normal")
        self.included_files.delete("1.0", "end")
        for rel in effective_included_files:
            self.included_files.insert("end", rel + "\n")
        self.included_files.configure(state="disabled")
        errors = self._validate(values)
        self.validation_text.configure(state="normal")
        self.validation_text.delete("1.0", "end")
        if errors:
            for item in errors:
                self.validation_text.insert("end", "• " + item + "\n")
        else:
            self.validation_text.insert("end", "Ready to export.\n")
        self.validation_text.configure(state="disabled")

    def _save_back_to_launcher_settings(self, values):
        s = self.master.settings
        s.author_key_file = values["author_key_file"]
        s.export_theme_name = values["theme_name"]
        s.export_theme_version = values["theme_version"]
        s.export_author_name = values["author_name"]
        s.export_freecad_version_tested = values["freecad_version_tested"]
        s.export_description = values["description"]
        s.export_copyright = values["copyright"]
        s.export_license = values["license"]
        s.export_license_terms = values["license_terms"]
        s.export_theme_package = THEME_PACKAGE_OPTION_COMPLETE
        s.export_require_external_qss = False
        s.export_external_qss_url = ""
        self.master.settings_path.write_text(json.dumps(asdict(self.master.settings), indent=2, ensure_ascii=False), encoding="utf-8")

    def _export_clicked(self):
        values = self._collect_values()
        errors = self._validate(values)
        if errors:
            self._refresh_summary()
            messagebox.showerror(APP_NAME, "\n".join(errors), parent=self)
            return
        self._save_back_to_launcher_settings(values)
        self.result = values
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()




class CreateShortcutDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, default_name: str = "FreeCAD", default_location: str = "") -> None:
        super().__init__(parent)
        self.title("Create Shortcut")
        self.resizable(True, False)
        self.result: dict[str, str] | None = None
        self.transient(parent)
        self.grab_set()

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        self.name_var = tk.StringVar(value=default_name)
        self.location_var = tk.StringVar(value=default_location)
        self.mode_var = tk.StringVar(value="user")

        ttk.Label(body, text="Name").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(body, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(body, text="Location").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(body, textvariable=self.location_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(body, text="Browse", command=self._browse_location).grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=4)

        mode_row = ttk.Frame(body)
        mode_row.grid(row=2, column=1, sticky="w", pady=(8, 4))
        ttk.Radiobutton(mode_row, text="User", variable=self.mode_var, value="user").pack(side="left")
        ttk.Radiobutton(mode_row, text="Creator", variable=self.mode_var, value="creator").pack(side="left", padx=(16, 0))

        actions = ttk.Frame(body)
        actions.grid(row=3, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(actions, text="Create", command=self._accept).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        self.minsize(max(460, self.winfo_reqwidth()), self.winfo_reqheight())

    def _browse_location(self) -> None:
        current = self.location_var.get().strip() or str(Path.home())
        path = None
        if platform.system().lower() == "darwin":
            path = _macos_choose_folder_path("Select Shortcut Location", current)
        if path is None:
            path = filedialog.askdirectory(title="Select Shortcut Location", initialdir=current)
        if path:
            self.location_var.set(path)

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        location = self.location_var.get().strip()
        mode = self.mode_var.get().strip().lower()
        if not name:
            messagebox.showerror(APP_NAME, "Shortcut Name is required.", parent=self)
            return
        if not location:
            messagebox.showerror(APP_NAME, "Shortcut Location is required.", parent=self)
            return
        if mode not in ("user", "creator"):
            messagebox.showerror(APP_NAME, "Please select User or Creator.", parent=self)
            return
        self.result = {"name": name, "location": location, "mode": mode}
        self.destroy()


class LicenseAndExternalAssetsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, metadata: dict[str, str], on_download: Callable[[], None]) -> None:
        super().__init__(parent)
        self.title("License and external assets")
        self.resizable(True, False)
        self.transient(parent)
        self.grab_set()
        self.metadata = metadata
        self.on_download = on_download
        self.completed = False

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        message = (
            "This theme contains Artwork only and requires external configuration and stylesheet files."
        )
        ttk.Label(body, text=message, wraplength=520, justify="left").grid(row=0, column=0, sticky="w")

        buttons = ttk.Frame(body)
        buttons.grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Button(buttons, text="License", command=self._show_license).pack(side="left")
        ttk.Button(buttons, text="License Notice", command=self._show_license_notice).pack(side="left", padx=(8, 0))

        self.accept_var = tk.BooleanVar(value=False)
        checkbox_text = (
            "I have read and agree to the License and the License Notice, and I understand that proceeding will download the required external assets."
        )
        ttk.Checkbutton(
            body,
            text=checkbox_text,
            variable=self.accept_var,
            command=self._sync_download_state,
        ).grid(row=2, column=0, sticky="w", pady=(14, 0))

        self.download_button = ttk.Button(body, text="Download Required External Assets", command=self._download_clicked)
        self.download_button.grid(row=3, column=0, sticky="w", pady=(12, 0))

        footer = ttk.Frame(body)
        footer.grid(row=4, column=0, sticky="e", pady=(12, 0))
        ttk.Button(footer, text="Close", command=self._close).pack(side="right")

        self._sync_download_state()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.update_idletasks()
        self.minsize(max(620, self.winfo_reqwidth()), self.winfo_reqheight())

    def _sync_download_state(self) -> None:
        self.download_button.configure(state=("normal" if self.accept_var.get() else "disabled"))

    def _show_license(self) -> None:
        content = str(self.metadata.get("license_text", "") or "").strip()
        if not content:
            messagebox.showinfo(APP_NAME, "No packaged license text is available in the loaded theme.", parent=self)
            return
        cast_parent = self.master
        if hasattr(cast_parent, "_show_scrollable_text_popup"):
            cast_parent._show_scrollable_text_popup("License", content, owner=self)

    def _show_license_notice(self) -> None:
        content = str(self.metadata.get("license_notice", "") or "").strip()
        if not content:
            messagebox.showinfo(APP_NAME, "No License Notice text is available in the loaded theme.", parent=self)
            return
        cast_parent = self.master
        if hasattr(cast_parent, "_show_scrollable_text_popup"):
            cast_parent._show_scrollable_text_popup("License Notice", content, owner=self)

    def _download_clicked(self) -> None:
        try:
            self.on_download()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            return
        self.completed = True
        messagebox.showinfo(APP_NAME, "Required external assets downloaded successfully.", parent=self)
        self.destroy()

    def _close(self) -> None:
        self.destroy()


class ThemeLauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry(f"{WINDOW_WIDTH}x1")
        self.minsize(WINDOW_WIDTH, 1)
        self.resizable(True, True)

        self.base_dir = _resource_base_dir()
        self.launcher_entry_path = _launcher_entry_path()
        self.settings_path = _settings_storage_path(self.base_dir)
        self.freecad_executable_fallback_path = _freecad_executable_fallback_path(self.base_dir)
        self.settings = self.load_settings()
        self.vars: dict[str, tk.Variable] = {}
        self.entries: dict[str, ttk.Entry] = {}
        self._resize_after_id = None

        self._build_ui()
        self._populate_ui_from_settings()
        self.refresh_status()
        self.after(50, self._update_dynamic_window_size)

    def load_settings(self) -> AppSettings:
        if self.settings_path.exists():
            try:
                settings = _load_app_settings_from_path(self.settings_path)
                persisted = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if "export_license" not in persisted or not str(getattr(settings, "export_license", "") or "").strip():
                    theme_folder_text = str(getattr(settings, "theme_folder", "") or "").strip()
                    if theme_folder_text:
                        theme_folder = Path(theme_folder_text).expanduser()
                        if theme_folder.exists() and theme_folder.is_dir():
                            settings.export_license = _detect_existing_license_choice(self.base_dir, theme_folder)
                        else:
                            settings.export_license = CUSTOM_LICENSE_OPTION
                    else:
                        settings.export_license = CUSTOM_LICENSE_OPTION
                if not str(getattr(settings, "freecad_executable", "") or "").strip():
                    fallback_executable = self._read_freecad_executable_fallback()
                    if fallback_executable:
                        settings.freecad_executable = fallback_executable
                return settings
            except Exception:
                pass

        return AppSettings()

    def _write_settings_file(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve settings owned by the FreeCAD workbench (for example,
        # theme_runtime_location), which are not AppSettings dataclass fields.
        existing = {}
        if self.settings_path.is_file():
            try:
                read_back = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(read_back, dict):
                    existing = read_back
            except (OSError, ValueError):
                pass
        existing.update(asdict(self.settings))
        # Use replace so a partially written JSON file cannot be observed.
        import tempfile as _etc_tempfile
        import os as _etc_os
        fd, temporary = _etc_tempfile.mkstemp(prefix=".etc-settings-", suffix=".json", dir=str(self.settings_path.parent))
        try:
            with _etc_os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(existing, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            _etc_os.replace(temporary, self.settings_path)
        finally:
            if _etc_os.path.exists(temporary):
                _etc_os.unlink(temporary)

    def save_settings(self) -> None:
        self._collect_ui_to_settings()
        self._write_settings_file()
        self.status("Settings saved.")

    def _persist_settings_silently(self) -> None:
        self._collect_ui_to_settings()
        self._write_settings_file()
        self._write_freecad_executable_fallback()

    def _write_freecad_executable_fallback(self, value: str | None = None) -> None:
        raw_value = str(value if value is not None else self._current_entry_text("freecad_executable") or getattr(self.settings, "freecad_executable", "") or "").strip()
        path = getattr(self, "freecad_executable_fallback_path", None)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if raw_value:
                path.write_text(raw_value, encoding="utf-8")
            elif path.exists():
                path.unlink()
        except Exception:
            pass

    def _read_freecad_executable_fallback(self) -> str:
        path = getattr(self, "freecad_executable_fallback_path", None)
        if path is None or not Path(path).exists():
            return ""
        try:
            return str(Path(path).read_text(encoding="utf-8")).strip()
        except Exception:
            return ""

    def _resolve_effective_freecad_executable(self) -> tuple[Path | None, str]:
        candidate_texts: list[str] = []

        def _remember(candidate: str) -> None:
            value = str(candidate or "").strip().strip('"').strip()
            if value and value not in candidate_texts:
                candidate_texts.append(value)

        _remember(self._current_entry_text("freecad_executable"))
        _remember(str(getattr(self.settings, "freecad_executable", "") or "").strip())
        _remember(self._read_freecad_executable_fallback())

        settings_candidates = [self.settings_path]
        legacy_local_settings_path = Path(__file__).resolve().parent / SETTINGS_FILE
        if legacy_local_settings_path not in settings_candidates:
            settings_candidates.append(legacy_local_settings_path)

        for settings_candidate in settings_candidates:
            if not settings_candidate.exists():
                continue
            try:
                persisted = json.loads(settings_candidate.read_text(encoding="utf-8"))
                _remember(str(persisted.get("freecad_executable", "") or "").strip())
            except Exception:
                pass

        autodetected = _autodetect_freecad_executable_path()
        if autodetected is not None:
            _remember(str(autodetected))

        first_nonempty = candidate_texts[0] if candidate_texts else ""
        for candidate_text in candidate_texts:
            resolved = _normalize_freecad_executable_path(candidate_text)
            if resolved is not None and resolved.exists():
                self.settings.freecad_executable = candidate_text
                if self.vars.get("freecad_executable") is not None:
                    try:
                        self.vars["freecad_executable"].set(candidate_text)
                    except Exception:
                        pass
                try:
                    self._write_settings_file()
                except Exception:
                    pass
                self._write_freecad_executable_fallback(candidate_text)
                return resolved, candidate_text
        return _normalize_freecad_executable_path(first_nonempty), first_nonempty

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(
            outer,
            text="External Theme Creator",
            font=("TkDefaultFont", 15, "bold"),
        )
        title.pack(anchor="w")

        mode_row = ttk.Frame(outer)
        mode_row.pack(fill="x", pady=(8, 0))

        self.vars["user_mode"] = tk.BooleanVar(value=True)
        self.vars["creator_mode"] = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            mode_row,
            text="User Mode",
            variable=self.vars["user_mode"],
            command=self._on_user_mode_changed,
        ).pack(side="left")

        ttk.Checkbutton(
            mode_row,
            text="Creator Mode",
            variable=self.vars["creator_mode"],
            command=self._on_creator_mode_changed,
        ).pack(side="left", padx=(18, 0))

        form = ttk.Frame(outer)
        form.pack(fill="x", expand=False, pady=(8, 0))
        form.columnconfigure(0, weight=1)

        self.user_mode_row = ttk.Frame(form)
        self.user_mode_row.grid(row=0, column=0, sticky="ew")
        self.user_mode_row.columnconfigure(1, weight=1)
        self.user_mode_row.columnconfigure(2, weight=0)
        self._add_path_row(self.user_mode_row, 0, "Theme", "theme_file", self.browse_theme_file)

        self.theme_copyright_var = tk.StringVar(value="")
        self.theme_license_notice_brief_var = tk.StringVar(value="")
        self.theme_license_var = tk.StringVar(value="")
        self.loaded_theme_metadata: dict[str, str] = {}

        self.theme_info_frame = ttk.Frame(self.user_mode_row)
        self.theme_info_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=(22, 22), pady=(2, 0))
        self.theme_info_frame.columnconfigure(0, weight=1)

        self.theme_copyright_message = tk.Message(
            self.theme_info_frame,
            textvariable=self.theme_copyright_var,
            justify="left",
            anchor="w",
            width=max(200, WINDOW_WIDTH - 120),
        )
        self.theme_copyright_message.grid(row=0, column=0, sticky="ew", pady=(4, 0))

        self.theme_license_notice_brief_message = tk.Message(
            self.theme_info_frame,
            textvariable=self.theme_license_notice_brief_var,
            justify="left",
            anchor="w",
            width=max(200, WINDOW_WIDTH - 120),
        )
        self.theme_license_notice_brief_message.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        self.theme_license_message = tk.Message(
            self.theme_info_frame,
            textvariable=self.theme_license_var,
            justify="left",
            anchor="w",
            width=max(200, WINDOW_WIDTH - 120),
        )
        self.theme_license_message.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        self.creator_mode_row = ttk.Frame(form)
        self.creator_mode_row.grid(row=0, column=0, sticky="ew")
        self.creator_mode_row.columnconfigure(1, weight=1)
        self._add_path_row(self.creator_mode_row, 0, "Theme Folder", "theme_folder", self.browse_theme_folder)

        self.actions = ttk.Frame(outer)
        self.actions.pack(fill="x", pady=(12, 0))
        self.cfg_instructions_button = ttk.Button(self.actions, text="CFG instructions", command=self.open_cfg_instructions)
        self.validate_button = ttk.Button(self.actions, text="Validate Theme Folder", command=self.validate_clicked)
        self.export_button = ttk.Button(self.actions, text="Export Theme", command=self.export_theme_clicked)
        self.launch_freecad_button = ttk.Button(self.actions, text="Launch FreeCAD", command=self.launch_freecad)
        self.launch_from_theme_button = ttk.Button(self.actions, text="Launch FreeCAD", command=self.launch_from_theme_clicked)
        self.show_license_button = ttk.Button(self.actions, text="License", command=self.show_loaded_theme_license)
        self.show_license_notice_button = ttk.Button(self.actions, text="License Notice", command=self.show_loaded_theme_license_notice)

        self.settings_section = CollapsibleSection(outer, "Settings", expanded=False, on_toggle=self._schedule_dynamic_window_size_update)
        self.settings_section.pack(fill="x", pady=(12, 0))
        settings_body = self.settings_section.body
        settings_body.columnconfigure(1, weight=1)

        self.vars["use_freecad_user_home"] = tk.BooleanVar(value=True)
        self.vars["use_external_icons"] = tk.BooleanVar(value=True)
        self.vars["close_after_freecad_launch"] = tk.BooleanVar(value=True)
        self.vars["extra_cli_args"] = tk.StringVar(value="")

        self._add_path_row(settings_body, 0, "FreeCAD executable", "freecad_executable", self.browse_freecad_executable)

        ttk.Checkbutton(
            settings_body,
            text="Set FREECAD_USER_HOME to a runtime folder",
            variable=self.vars["use_freecad_user_home"],
            command=self.refresh_status,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(
            settings_body,
            text="Use external icons",
            variable=self.vars["use_external_icons"],
            command=self._on_use_external_icons_changed,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Checkbutton(
            settings_body,
            text="Close after FreeCAD launch",
            variable=self.vars["close_after_freecad_launch"],
            command=self.refresh_status,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=2)

        ttk.Button(
            settings_body,
            text="Create Shortcut",
            command=self.create_shortcut_clicked,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

        ttk.Button(
            settings_body,
            text="Theme Configuration Diagnostics",
            command=self.run_theme_configuration_diagnostics,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))

        self.status_frame = ttk.LabelFrame(outer, text="Status", padding=10)
        self.status_frame.pack(fill="both", expand=True, pady=(12, 0))

        self.status_text = tk.Text(self.status_frame, height=20, wrap="word")
        self.status_text.pack(fill="both", expand=True)
        self.status_text.configure(state="disabled")

        self.bind("<Configure>", self._on_main_window_configure, add="+")
        self._update_theme_message_wraplengths()

        self._update_mode_ui()
        self.after_idle(self._schedule_dynamic_window_size_update)

    def _on_main_window_configure(self, _event=None) -> None:
        self._update_theme_message_wraplengths()

    def _update_theme_message_wraplengths(self) -> None:
        try:
            container_width = self.theme_info_frame.winfo_width()
        except Exception:
            container_width = 0
        if not container_width or container_width <= 1:
            try:
                container_width = self.user_mode_row.winfo_width() - 44
            except Exception:
                container_width = WINDOW_WIDTH - 88
        available_width = max(260, container_width - 8)
        for widget in (
            getattr(self, "theme_copyright_message", None),
            getattr(self, "theme_license_notice_brief_message", None),
            getattr(self, "theme_license_message", None),
        ):
            if widget is not None:
                try:
                    widget.configure(width=available_width)
                except Exception:
                    pass

    def _theme_file_loaded(self) -> bool:
        theme_text = self.vars["theme_file"].get().strip() if "theme_file" in self.vars else ""
        if not theme_text:
            return False
        theme_path = Path(theme_text).expanduser()
        return theme_path.exists() and theme_path.is_file()

    def _show_scrollable_text_popup(self, title: str, content: str, owner: tk.Misc | None = None) -> None:
        popup_parent = owner if owner is not None else self
        popup = tk.Toplevel(popup_parent)
        popup.title(title)
        try:
            popup.transient(popup_parent)
        except Exception:
            popup.transient(self)
        popup.resizable(True, True)
        popup.minsize(520, 360)

        shell = ttk.Frame(popup, padding=12)
        shell.pack(fill="both", expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)

        text_widget = tk.Text(shell, wrap="word")
        text_widget.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(shell, orient="vertical", command=text_widget.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text_widget.configure(yscrollcommand=scroll.set)

        text_widget.insert("1.0", content)
        text_widget.configure(state="disabled")

        def _close_popup() -> None:
            try:
                popup.grab_release()
            except Exception:
                pass
            popup.destroy()
            if owner is not None:
                try:
                    owner.grab_set()
                    owner.focus_force()
                except Exception:
                    pass

        buttons = ttk.Frame(shell)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Close", command=_close_popup).pack(side="right")

        popup.protocol("WM_DELETE_WINDOW", _close_popup)
        popup.update_idletasks()
        popup.geometry("700x600")
        try:
            popup.grab_set()
        except Exception:
            pass
        try:
            popup.attributes("-topmost", True)
            popup.after(250, lambda: popup.attributes("-topmost", False))
        except Exception:
            pass
        popup.focus_force()

    def show_loaded_theme_license_notice(self) -> None:
        metadata = getattr(self, "loaded_theme_metadata", {}) or {}
        content = str(metadata.get("license_notice", "") or "").strip()
        if not content:
            messagebox.showinfo(APP_NAME, "No License Notice text is available in the loaded theme.", parent=self)
            return
        self._show_scrollable_text_popup("License Notice", content)

    def show_loaded_theme_license(self) -> None:
        metadata = getattr(self, "loaded_theme_metadata", {}) or {}
        content = str(metadata.get("license_text", "") or "").strip()
        if not content:
            messagebox.showinfo(APP_NAME, "No packaged license text is available in the loaded theme.", parent=self)
            return
        self._show_scrollable_text_popup("License", content)

    def _loaded_theme_requires_external_assets(self, metadata: dict[str, str] | None = None) -> bool:
        info = metadata if metadata is not None else (getattr(self, "loaded_theme_metadata", {}) or {})
        if not info:
            return False
        if not _is_artwork_only_theme_package(info.get("theme_package", "")):
            return False
        return info.get("require_external_cfg") == "1" or info.get("require_external_qss") == "1"

    def _download_required_external_assets_from_metadata(self, metadata: dict[str, str]) -> dict[str, Path]:
        self._persist_critical_paths()
        theme_id = str(metadata.get("theme_id", "") or "").strip()
        if not theme_id:
            raise LauncherError("The loaded theme is missing a valid theme_id.")
        assets_dir = _theme_external_assets_dir(theme_id)
        assets_dir.mkdir(parents=True, exist_ok=True)
        stored = _read_external_assets_metadata(theme_id)
        result: dict[str, Path] = {}

        if metadata.get("require_external_cfg") == "1":
            cfg_url = str(metadata.get("external_cfg_url", "") or "").strip()
            cfg_filename = str(metadata.get("external_cfg_filename", "") or "").strip() or _external_asset_filename_from_url(cfg_url, ".cfg")
            cfg_bytes = _download_url_bytes(cfg_url, expected_suffix=".cfg")
            cfg_path = assets_dir / cfg_filename
            cfg_path.write_bytes(cfg_bytes)
            result["cfg"] = cfg_path
            stored["cfg"] = {
                "url": cfg_url,
                "filename": cfg_filename,
                "sha256": _sha256_bytes(cfg_bytes),
                "downloaded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

        if metadata.get("require_external_qss") == "1":
            qss_url = str(metadata.get("external_qss_url", "") or "").strip()
            qss_filename = str(metadata.get("external_qss_filename", "") or "").strip() or _external_asset_filename_from_url(qss_url, ".qss")
            qss_bytes = _download_url_bytes(qss_url, expected_suffix=".qss")
            qss_path = assets_dir / qss_filename
            qss_path.write_bytes(qss_bytes)
            result["qss"] = qss_path
            stored["qss"] = {
                "url": qss_url,
                "filename": qss_filename,
                "sha256": _sha256_bytes(qss_bytes),
                "downloaded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

        _write_external_assets_metadata(theme_id, stored)
        try:
            self._persist_settings_silently()
        except Exception:
            pass
        return result

    def _validate_required_external_assets(self, manifest: dict[str, object]) -> tuple[dict[str, Path], list[str]]:
        theme_id = str(manifest.get("theme_id", "") or "").strip()
        result: dict[str, Path] = {}
        errors: list[str] = []
        stored = _read_external_assets_metadata(theme_id)
        assets_dir = _theme_external_assets_dir(theme_id)

        if bool(manifest.get("require_external_cfg")):
            cfg_filename = str(manifest.get("external_cfg_filename", "") or "").strip()
            cfg_path = assets_dir / cfg_filename
            if not cfg_filename or not cfg_path.exists() or not cfg_path.is_file():
                errors.append(f"Required external configuration (.cfg) is missing:\n{cfg_path}")
            else:
                result["cfg"] = cfg_path

        if bool(manifest.get("require_external_qss")):
            qss_filename = str(manifest.get("external_qss_filename", "") or "").strip()
            qss_path = assets_dir / qss_filename
            qss_meta = stored.get("qss") if isinstance(stored.get("qss"), dict) else {}
            expected_hash = str(qss_meta.get("sha256", "") or "").strip()
            if not qss_filename or not qss_path.exists() or not qss_path.is_file():
                errors.append(f"Required external style-sheet (.qss) is missing:\n{qss_path}")
            elif not expected_hash:
                errors.append("Required external style-sheet (.qss) metadata is missing. Please download the required external assets again.")
            else:
                current_hash = _sha256_path(qss_path)
                if current_hash != expected_hash:
                    errors.append("Required external style-sheet (.qss) has been modified or is invalid. Please download the required external assets again.")
                else:
                    result["qss"] = qss_path

        return result, errors

    def _prompt_for_required_external_assets(self, theme_file: Path, metadata: dict[str, str]) -> bool:
        if not self._loaded_theme_requires_external_assets(metadata):
            return True
        dialog = LicenseAndExternalAssetsDialog(
            self,
            metadata,
            on_download=lambda: self._download_required_external_assets_from_metadata(metadata),
        )
        self.wait_window(dialog)
        return bool(dialog.completed)

    def _ensure_required_external_assets_ready(self, theme_file: Path, manifest: dict[str, object]) -> dict[str, Path]:
        metadata = _read_theme_package_metadata(theme_file)
        if not self._loaded_theme_requires_external_assets(metadata):
            return {}
        assets, errors = self._validate_required_external_assets(manifest)
        if not errors:
            return assets
        self._prompt_for_required_external_assets(theme_file, metadata)
        assets, errors = self._validate_required_external_assets(manifest)
        if errors:
            raise LauncherError("\n".join(errors))
        return assets

    def _update_dynamic_window_size(self) -> None:
        self.update_idletasks()

        req_width = WINDOW_WIDTH
        req_height = max(1, self.winfo_reqheight())

        x = self.winfo_x()
        y = self.winfo_y()

        self.minsize(WINDOW_WIDTH, 1)
        self.maxsize(WINDOW_WIDTH, 10000)
        self.geometry(f"{req_width}x{req_height}+{x}+{y}")
        self.update_idletasks()

    def _schedule_dynamic_window_size_update(self) -> None:
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.after(25, self._update_dynamic_window_size)

    def _current_entry_text(self, key: str) -> str:
        entry = self.entries.get(key)
        if entry is not None:
            try:
                return str(entry.get()).strip()
            except Exception:
                pass
        var = self.vars.get(key)
        if var is not None:
            try:
                return str(var.get()).strip()
            except Exception:
                pass
        return str(getattr(self.settings, key, "") or "").strip()

    def _persist_path_field(self, key: str) -> None:
        if not hasattr(self.settings, key):
            return
        value = self._current_entry_text(key)
        if key in self.vars:
            try:
                self.vars[key].set(value)
            except Exception:
                pass
        setattr(self.settings, key, value)
        try:
            self._write_settings_file()
        except Exception:
            pass
        if key == "freecad_executable":
            self._write_freecad_executable_fallback(value)

    def _persist_critical_paths(self) -> None:
        for key in ("freecad_executable", "theme_folder", "theme_file"):
            self._persist_path_field(key)

    def _add_path_row(self, parent: ttk.Frame, row: int, label: str, key: str, browse_command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        self.vars[key] = tk.StringVar(value="")
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        self.entries[key] = entry
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        def _on_key_release(_e, _key=key):
            self.refresh_status()
            if _key in {"freecad_executable", "theme_folder", "theme_file"}:
                try:
                    self.after_idle(lambda: self._persist_path_field(_key))
                except Exception:
                    pass
        entry.bind("<KeyRelease>", _on_key_release)
        entry.bind("<FocusOut>", lambda _e, _key=key: self._persist_path_field(_key))
        ttk.Button(parent, text="Browse", command=browse_command).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=4)

    def _refresh_selected_theme_metadata(self) -> None:
        theme_text = self.vars["theme_file"].get().strip() if "theme_file" in self.vars else ""
        copyright_text = ""
        license_notice_brief_text = ""
        license_text = ""
        self.loaded_theme_metadata = {}
        if theme_text:
            theme_path = Path(theme_text).expanduser()
            if theme_path.exists() and theme_path.is_file():
                metadata = _read_theme_package_metadata(theme_path)
                self.loaded_theme_metadata = metadata
                copyright_value = metadata.get("copyright", "").strip()
                license_notice_brief_value = metadata.get("license_notice_brief", "").strip()
                license_value = metadata.get("license_terms", "").strip()
                if copyright_value:
                    copyright_text = f"Copyright:  {copyright_value}"
                if license_notice_brief_value:
                    license_notice_brief_text = f"License Notice Brief:  {license_notice_brief_value}"
                if license_value:
                    license_text = f"License Brief:  {license_value}"
        self.theme_copyright_var.set(copyright_text)
        self.theme_license_notice_brief_var.set(license_notice_brief_text)
        self.theme_license_var.set(license_text)
        self._update_theme_action_buttons()
        self._update_theme_message_wraplengths()
        self._schedule_dynamic_window_size_update()

    def _set_mode(self, mode: str) -> None:
        is_user_mode = mode == "user"
        self.vars["user_mode"].set(is_user_mode)
        self.vars["creator_mode"].set(not is_user_mode)
        self._update_mode_ui()
        self.refresh_status()

    def _on_user_mode_changed(self) -> None:
        if self.vars["user_mode"].get():
            self._set_mode("user")
        else:
            self._set_mode("creator")

    def _on_creator_mode_changed(self) -> None:
        if self.vars["creator_mode"].get():
            self._set_mode("creator")
        else:
            self._set_mode("user")

    def _update_theme_action_buttons(self) -> None:
        self.show_license_button.pack_forget()
        self.show_license_notice_button.pack_forget()
        if bool(self.vars["user_mode"].get()) and self._theme_file_loaded():
            self.show_license_button.pack(side="left")
            self.show_license_notice_button.pack(side="left", padx=(8, 0))

    def _update_mode_ui(self) -> None:
        is_user_mode = bool(self.vars["user_mode"].get())

        self.cfg_instructions_button.pack_forget()
        self.validate_button.pack_forget()
        self.export_button.pack_forget()
        self.launch_freecad_button.pack_forget()
        self.launch_from_theme_button.pack_forget()
        self.show_license_button.pack_forget()
        self.show_license_notice_button.pack_forget()
        self.status_frame.pack_forget()

        if is_user_mode:
            self.user_mode_row.grid()
            self.creator_mode_row.grid_remove()
            self._update_theme_action_buttons()
            self.launch_from_theme_button.pack(side="right")
        else:
            self.user_mode_row.grid_remove()
            self.creator_mode_row.grid()
            self.cfg_instructions_button.pack(side="left")
            self.validate_button.pack(side="left", padx=(8, 0))
            self.export_button.pack(side="left", padx=(8, 0))
            self.launch_freecad_button.pack(side="right")
            self.status_frame.pack(fill="both", expand=True, pady=(12, 0))

        self.update_idletasks()
        self._update_theme_message_wraplengths()
        self._schedule_dynamic_window_size_update()

    def _populate_ui_from_settings(self) -> None:
        launch_mode = getattr(self.settings, "launch_mode", "user")
        for key, var in self.vars.items():
            if key == "use_external_icons":
                var.set(bool(self.settings.enable_external_icon_theme or self.settings.prefer_external_icons))
                continue
            if key in ("user_mode", "creator_mode"):
                continue
            if hasattr(self.settings, key):
                var.set(getattr(self.settings, key))
        self._sync_external_icon_settings_from_ui()
        self._refresh_selected_theme_metadata()
        self._set_mode("creator" if launch_mode == "creator" else "user")

    def _collect_ui_to_settings(self) -> None:
        self._sync_external_icon_settings_from_ui()
        self.settings.launch_mode = "user" if self.vars["user_mode"].get() else "creator"
        for key, var in self.vars.items():
            if key in ("use_external_icons", "user_mode", "creator_mode"):
                continue
            if hasattr(self.settings, key):
                if key in {"freecad_executable", "theme_folder", "theme_file"}:
                    setattr(self.settings, key, self._current_entry_text(key))
                else:
                    setattr(self.settings, key, var.get())

    def _sync_external_icon_settings_from_ui(self) -> None:
        use_external_icons = bool(self.vars["use_external_icons"].get())
        self.settings.enable_external_icon_theme = use_external_icons
        self.settings.prefer_external_icons = use_external_icons

    def _on_use_external_icons_changed(self) -> None:
        self._sync_external_icon_settings_from_ui()
        self.refresh_status()


    def browse_freecad_executable(self) -> None:
        system = platform.system().lower()
        current = self.vars["freecad_executable"].get().strip()
        current_path = Path(current).expanduser() if current else None

        initialdir_path: Path | None = None
        if current_path and current_path.exists():
            if system == "darwin":
                app_root = None
                for candidate in [current_path, *current_path.parents]:
                    if candidate.suffix.lower() == ".app":
                        app_root = candidate
                        break
                initialdir_path = app_root.parent if app_root is not None else current_path.parent
            else:
                initialdir_path = current_path.parent
        initialdir = str(initialdir_path) if initialdir_path else str(Path.home())

        if system == "darwin":
            path = _macos_choose_application_path("Select the FreeCAD application.", "Select FreeCAD.app")
            if path == "":
                return
            if path is None:
                path = filedialog.askdirectory(
                    title="Select FreeCAD.app",
                    initialdir=initialdir,
                    mustexist=True,
                )
            if not path:
                return
            selected = Path(path).expanduser()
            if selected.suffix.lower() != ".app":
                messagebox.showerror(APP_NAME, "Please select the FreeCAD.app application.")
                return
            normalized = _normalize_freecad_executable_path(selected)
            if normalized is None or not normalized.exists():
                messagebox.showerror(APP_NAME, f"Could not find the FreeCAD executable inside:\n{selected}")
                return
            self.vars["freecad_executable"].set(str(selected))
            self._persist_settings_silently()
            self.refresh_status()
            return

        if system == "linux":
            path = filedialog.askopenfilename(
                title="Select FreeCAD.AppImage",
                initialdir=initialdir,
                filetypes=[("FreeCAD AppImage", "*.AppImage"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askopenfilename(
                title="Select FreeCAD executable",
                initialdir=initialdir,
                filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
            )
        if path:
            self.vars["freecad_executable"].set(path)
            self._persist_settings_silently()
            self.refresh_status()

    def open_cfg_instructions(self) -> None:
        CFGInstructionsDialog(self)

    def browse_theme_folder(self) -> None:
        current = self.vars["theme_folder"].get().strip() or str(Path.home())
        path = None
        if platform.system().lower() == "darwin":
            path = _macos_choose_folder_path("Select Theme Folder", current)
        if path is None:
            path = filedialog.askdirectory(title="Select Theme Folder", initialdir=current)
        if path:
            self.vars["theme_folder"].set(path)
            self._persist_settings_silently()
            self.refresh_status()


    def browse_theme_file(self) -> None:
        current = self.vars["theme_file"].get().strip()
        if current:
            initialdir = str(Path(current).expanduser().parent)
        else:
            initialdir = self.vars["theme_folder"].get().strip() or str(Path.home())
        path = None
        if platform.system().lower() == "darwin":
            path = _macos_choose_file_path("Select Theme File", initialdir)
        if path is None:
            path = filedialog.askopenfilename(
                title="Select Theme File",
                initialdir=initialdir,
                filetypes=[("Theme files", f"*{THEME_PACKAGE_EXTENSION}"), ("All files", "*.*")],
            )
        if path:
            self.vars["theme_file"].set(path)
            self._persist_settings_silently()
            self._refresh_selected_theme_metadata()
            self.refresh_status()
            metadata = getattr(self, "loaded_theme_metadata", {}) or {}
            if self._loaded_theme_requires_external_assets(metadata):
                self._prompt_for_required_external_assets(Path(path).expanduser(), metadata)

    def _scan_theme_folder_for_export(self) -> dict[str, object]:
        self._collect_ui_to_settings()
        folder_text = self.settings.theme_folder.strip()
        result: dict[str, object] = {
            "theme_folder": folder_text,
            "included_files": [],
            "counts": {".svg": 0, ".png": 0, ".qss": 0},
            "detected_theme_configuration": "",
            "detected_splash": "",
        }
        if not folder_text:
            return result
        theme_folder = Path(folder_text).expanduser()
        if not theme_folder.exists() or not theme_folder.is_dir():
            return result

        included_files: list[str] = []
        for path in sorted(theme_folder.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(theme_folder).as_posix()
            if any(rel.startswith(f"{n}/") or f"/{n}/" in rel for n in (RUNTIME_DIR_NAME, ".UI_Launcher_runtime")):
                continue
            if path.suffix.lower() not in EXPORTABLE_THEME_EXTENSIONS:
                continue
            if path.suffix.lower() == ".py" and not rel.startswith("scripts/"):
                continue
            if not _is_safe_relpath(rel):
                continue
            included_files.append(rel)

        # Only top-level package-control files are detected here.
        # Legacy .cfg files are intentionally not exportable.
        top_level_export_files = [
            rel for rel in included_files
            if "/" not in rel
        ]
        counts = _count_suffixes(included_files)
        theme_configs = [rel for rel in top_level_export_files if Path(rel).name.lower() == THEME_CONFIGURATION_FILENAME.lower()]

        result["included_files"] = included_files
        result["counts"] = counts
        result["detected_theme_configuration"] = theme_configs[0] if len(theme_configs) == 1 else ""
        result["detected_splash"] = _detect_splash_relpath(included_files)
        return result

    def _prepare_license_file_for_export(self, values: dict[str, str], theme_folder: Path) -> str:
        license_choice = values.get("license", "").strip()
        target_path = theme_folder / THEME_LICENSE_RELPATH
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if license_choice == CUSTOM_LICENSE_OPTION:
            if not target_path.exists() or not target_path.is_file():
                raise LauncherError(f'Custom License requires "{THEME_LICENSE_RELPATH}" inside the Theme Folder.')
            return THEME_LICENSE_RELPATH
        source_path = _license_source_path(self.base_dir, license_choice)
        if source_path is None or not source_path.exists() or not source_path.is_file():
            raise LauncherError(f'Selected CC license file was not found in "{CC_LICENSES_DIR_NAME}".')
        shutil.copy2(source_path, target_path)
        return THEME_LICENSE_RELPATH

    def _create_theme_package(self, values: dict[str, str], scan: dict[str, object], output_path: Path) -> tuple[dict[str, object], Path]:
        theme_folder = Path(self.settings.theme_folder).expanduser().resolve()
        theme_package = THEME_PACKAGE_OPTION_COMPLETE
        included_files = _effective_export_file_list(scan, theme_folder, values.get("license", ""), theme_package)
        license_relpath = self._prepare_license_file_for_export(values, theme_folder)
        if license_relpath and license_relpath not in included_files:
            included_files.append(license_relpath)
        included_files = sorted(set(included_files), key=str.lower)
        artwork_only = _is_artwork_only_theme_package(theme_package)
        default_cfg_relpath = ""  # Legacy manifest field; new exports never package .cfg files.
        theme_configuration_relpath = "" if artwork_only else str(scan.get("detected_theme_configuration", "") or "")
        default_splash_relpath = str(scan.get("detected_splash", "") or "")
        external_cfg_url = ""  # Legacy manifest field; external .cfg is no longer supported for new exports.
        external_qss_url = values.get("external_qss_url", "") if artwork_only and values.get("require_external_qss") else ""
        external_cfg_filename = ""
        external_qss_filename = _external_asset_filename_from_url(external_qss_url, ".qss") if external_qss_url else ""
        private_key, public_pem, fingerprint = _load_author_private_key(Path(values["author_key_file"]).expanduser())
        payload_buffer = io.BytesIO()
        with zipfile.ZipFile(payload_buffer, "w", zipfile.ZIP_DEFLATED) as payload_zip:
            for rel in included_files:
                if rel == CUSTOM_LICENSE_BRIEF_RELPATH:
                    payload_zip.writestr(f"files/{rel}", str(values.get("license_terms", "")), compress_type=zipfile.ZIP_DEFLATED)
                else:
                    payload_zip.write(theme_folder / rel, f"files/{rel}")
        encrypted_payload = _encrypt_payload(payload_buffer.getvalue())
        manifest = {
            "schema_version": THEME_SCHEMA_VERSION,
            "package_type": THEME_PACKAGE_TYPE,
            "theme_name": values["theme_name"],
            "theme_id": values["theme_id"],
            "theme_version": values["theme_version"],
            "author_name": values["author_name"],
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "freecad_version_tested": values["freecad_version_tested"],
            "launcher_version": APP_VERSION,
            "theme_creator_version": str(values.get("theme_creator_version", "") or ""),
            "description": values["description"],
            "copyright": values["copyright"],
            "license": values["license"],
            "license_terms": values["license_terms"],
            "theme_package": _theme_package_manifest_value(theme_package),
            "require_external_cfg": False,
            "external_cfg_url": external_cfg_url,
            "external_cfg_filename": external_cfg_filename,
            "require_external_qss": bool(artwork_only and values.get("require_external_qss")),
            "external_qss_url": external_qss_url,
            "external_qss_filename": external_qss_filename,
            "payload_encryption": THEME_PAYLOAD_ENCRYPTION,
            "payload_hash_sha256": hashlib.sha256(encrypted_payload).hexdigest(),
            "payload_size_bytes": len(encrypted_payload),
            "payload_file_count": len(included_files),
            "default_cfg_relpath": default_cfg_relpath,
            "theme_configuration_relpath": theme_configuration_relpath,
            "default_splash_relpath": default_splash_relpath,
            "included_files": included_files,
        }
        signature = private_key.sign(_canonical_manifest_bytes(manifest))
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as outer_zip:
            outer_zip.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            outer_zip.writestr("author_public_key.pem", public_pem)
            outer_zip.writestr("signature.sig", base64.b64encode(signature).decode("ascii"))
            outer_zip.writestr("payload.enc", encrypted_payload)
        return manifest, output_path

    def export_theme_clicked(self) -> None:
        self._collect_ui_to_settings()
        scan = self._scan_theme_folder_for_export()
        dialog = ExportThemeDialog(self, scan)
        self.wait_window(dialog)
        if not dialog.result:
            self.append_status("Export Theme canceled.")
            return
        try:
            default_name = f"{dialog.result['theme_id']}_v{dialog.result['theme_version']}{THEME_PACKAGE_EXTENSION}"
            save_path = filedialog.asksaveasfilename(
                title="Export Theme",
                defaultextension=THEME_PACKAGE_EXTENSION,
                initialfile=default_name,
                filetypes=[("Theme files", f"*{THEME_PACKAGE_EXTENSION}"), ("All files", "*.*")],
            )
            if not save_path:
                self.append_status("Export Theme canceled.")
                return
            manifest, output_file = self._create_theme_package(dialog.result, scan, Path(save_path))
            self.vars["theme_file"].set(str(output_file))
            self.clear_status()
            self.append_status("Theme exported successfully.")
            self.append_status(f"Theme Name: {manifest['theme_name']}")
            self.append_status(f"Theme ID: {manifest['theme_id']}")
            self.append_status(f"Theme Version: {manifest['theme_version']}")
            self.append_status(f"Author Name: {manifest['author_name']}")
            self.append_status(f"Included Files: {manifest['payload_file_count']}")
            self.append_status(f"Default CFG: {manifest['default_cfg_relpath']}")
            self.append_status(f"Output: {output_file}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            self.append_status(f"Export Theme failed: {exc}")

    def _read_theme_package(self, theme_file: Path) -> tuple[dict[str, object], bytes, str, bytes]:
        with zipfile.ZipFile(theme_file, "r") as outer_zip:
            names = set(outer_zip.namelist())
            required = {"manifest.json", "author_public_key.pem", "signature.sig", "payload.enc"}
            missing = sorted(required - names)
            if missing:
                raise LauncherError("Theme package is missing required files: " + ", ".join(missing))
            manifest = json.loads(outer_zip.read("manifest.json").decode("utf-8"))
            public_pem = outer_zip.read("author_public_key.pem")
            signature_b64 = outer_zip.read("signature.sig").decode("ascii").strip()
            payload_enc = outer_zip.read("payload.enc")
        return manifest, public_pem, signature_b64, payload_enc

    def _validate_theme_manifest(self, manifest: dict[str, object]) -> None:
        required = [
            "schema_version", "package_type", "theme_name", "theme_id", "theme_version",
            "author_name", "created_utc", "freecad_version_tested", "launcher_version",
            "description", "copyright", "license_terms", "payload_encryption",
            "payload_hash_sha256", "payload_size_bytes", "payload_file_count",
            "default_cfg_relpath", "included_files", "theme_package",
            "require_external_cfg", "external_cfg_url", "external_cfg_filename",
            "require_external_qss", "external_qss_url", "external_qss_filename",
        ]
        missing = [key for key in required if key not in manifest]
        if missing:
            raise LauncherError("Theme manifest is missing required fields: " + ", ".join(missing))
        if manifest["schema_version"] != THEME_SCHEMA_VERSION:
            raise LauncherError(f"Unsupported theme schema version: {manifest['schema_version']}")
        if manifest["package_type"] != THEME_PACKAGE_TYPE:
            raise LauncherError("Selected file is not a supported External Theme Creator theme package.")
        if manifest["payload_encryption"] != THEME_PAYLOAD_ENCRYPTION:
            raise LauncherError("Unsupported theme payload encryption.")
        if not _slugify_theme_id(str(manifest["theme_id"])) == str(manifest["theme_id"]):
            raise LauncherError("Theme package contains an invalid theme_id.")
        included_files = manifest["included_files"]
        if not isinstance(included_files, list) or not included_files:
            raise LauncherError("Theme package included_files is invalid.")
        for rel in included_files:
            if not isinstance(rel, str) or not _is_safe_relpath(rel):
                raise LauncherError("Theme package contains an unsafe file path.")
        artwork_only = _is_artwork_only_theme_package(str(manifest.get("theme_package", "")))
        cfg_rel = str(manifest["default_cfg_relpath"] or "")
        if artwork_only:
            if cfg_rel and cfg_rel not in included_files:
                raise LauncherError("Theme package default_cfg_relpath is invalid.")
        else:
            theme_config_rel = str(manifest.get("theme_configuration_relpath", "") or "")
            if not theme_config_rel:
                matches = [rel for rel in included_files if Path(rel).name.lower() == THEME_CONFIGURATION_FILENAME.lower()]
                theme_config_rel = matches[0] if len(matches) == 1 else ""
            if cfg_rel:
                if cfg_rel not in included_files:
                    raise LauncherError("Theme package default_cfg_relpath is missing from included_files.")
            elif not theme_config_rel or theme_config_rel not in included_files:
                raise LauncherError(f'Theme package contains neither a default .cfg nor {THEME_CONFIGURATION_FILENAME}.')
        splash_rel = str(manifest.get("default_splash_relpath", "") or "")
        if splash_rel and splash_rel not in included_files:
            raise LauncherError("Theme package default_splash_relpath is missing from included_files.")
        if artwork_only:
            if bool(manifest.get("require_external_cfg")):
                _external_asset_filename_from_url(str(manifest.get("external_cfg_url", "") or ""), ".cfg")
                if not str(manifest.get("external_cfg_filename", "") or ""):
                    raise LauncherError("Theme package is missing external_cfg_filename.")
            if bool(manifest.get("require_external_qss")):
                _external_asset_filename_from_url(str(manifest.get("external_qss_url", "") or ""), ".qss")
                if not str(manifest.get("external_qss_filename", "") or ""):
                    raise LauncherError("Theme package is missing external_qss_filename.")

    def _extract_theme_payload(self, manifest: dict[str, object], payload_enc: bytes) -> tuple[Path, Path]:
        if hashlib.sha256(payload_enc).hexdigest() != str(manifest["payload_hash_sha256"]):
            raise LauncherError("Theme package payload does not match the signed manifest.")
        payload_bytes = _decrypt_payload(payload_enc)
        extraction_root = _make_obscured_temp_dir()
        theme_root = extraction_root / "theme_files"
        theme_root.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as payload_zip:
                names = payload_zip.namelist()
                expected = [f"files/{rel}" for rel in manifest["included_files"]]
                for name in names:
                    if not name.startswith("files/"):
                        raise LauncherError("Theme payload contains an unexpected entry.")
                for rel in manifest["included_files"]:
                    if f"files/{rel}" not in names:
                        raise LauncherError(f"Theme payload is missing expected file: {rel}")
                for rel in manifest["included_files"]:
                    if not _is_safe_relpath(rel):
                        raise LauncherError("Theme payload contains an unsafe path.")
                    target = (theme_root / rel).resolve()
                    if theme_root.resolve() not in target.parents and target != theme_root.resolve():
                        raise LauncherError("Theme payload extraction path is unsafe.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with payload_zip.open(f"files/{rel}") as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
            return extraction_root, theme_root
        except Exception:
            shutil.rmtree(extraction_root, ignore_errors=True)
            raise

    def launch_from_theme_clicked(self) -> None:
        self._persist_critical_paths()
        self._collect_ui_to_settings()
        try:
            self._persist_settings_silently()
        except Exception:
            pass
        try:
            resolved_freecad_executable, raw_freecad_executable_text = self._require_freecad_executable_now()
            theme_text = self.settings.theme_file.strip()
            if not theme_text:
                messagebox.showerror(APP_NAME, "Theme is not selected.")
                self.append_status("Launch from Theme failed: Theme is not selected.")
                return
            theme_file = Path(theme_text).expanduser()
            if not theme_file.exists() or not theme_file.is_file():
                raise LauncherError("Theme does not exist or is not a file.")
            manifest, public_pem, signature_b64, payload_enc = self._read_theme_package(theme_file)
            self._validate_theme_manifest(manifest)
            _verify_signature(manifest, public_pem, signature_b64)

            external_assets = self._ensure_required_external_assets_ready(theme_file, manifest)
            extraction_root, theme_root = self._extract_theme_payload(manifest, payload_enc)

            packaged_cfg: Path | None = None
            cfg_rel = str(manifest.get("default_cfg_relpath", "") or "").strip()
            if cfg_rel:
                candidate_cfg = theme_root / cfg_rel
                if candidate_cfg.exists() and candidate_cfg.is_file():
                    packaged_cfg = candidate_cfg

            if bool(manifest.get("require_external_cfg")):
                cfg_source = external_assets.get("cfg")
                if cfg_source is None or not cfg_source.exists() or not cfg_source.is_file():
                    raise LauncherError("Required external configuration (.cfg) is not available. Please download the required external assets again.")
                cfg_writeback_target = cfg_source
            else:
                theme_config_rel = str(manifest.get("theme_configuration_relpath", "") or "").strip()
                if not theme_config_rel:
                    matches = [rel for rel in manifest.get("included_files", []) if Path(str(rel)).name.lower() == THEME_CONFIGURATION_FILENAME.lower()]
                    theme_config_rel = str(matches[0]) if len(matches) == 1 else ""
                if theme_config_rel:
                    theme_config_path = theme_root / theme_config_rel
                    if not theme_config_path.exists() or not theme_config_path.is_file():
                        raise LauncherError(f"{THEME_CONFIGURATION_FILENAME} was not found after extraction.")
                    theme_config = _load_theme_configuration(theme_config_path)
                    output_filename = str(theme_config["output"]["filename"])
                    permanent_cfg = _theme_state_dir(str(manifest["theme_id"])) / output_filename
                    permanent_cfg.parent.mkdir(parents=True, exist_ok=True)
                    if not permanent_cfg.exists():
                        # Apply Theme must locate version-scoped FreeCAD profiles too
                        # (for example ~/.config/FreeCAD/v1-1/user.cfg on Linux).
                        # Prefer the selected FreeCAD build's reported config path.
                        source_user_cfg = self._probe_freecad_user_cfg(resolved_freecad_executable)
                        if source_user_cfg is None:
                            candidates = [p for p in _freecad_user_cfg_candidates()
                                          if p.is_file()]
                            # Prefer the most recently modified profile if several
                            # FreeCAD versions have their own user.cfg.
                            if candidates:
                                source_user_cfg = max(candidates, key=lambda p: p.stat().st_mtime)
                        if source_user_cfg is None:
                            raise LauncherError(
                                "FreeCAD's user.cfg was not found.\n\n"
                                "ETC checked FreeCAD's reported configuration path and "
                                "the usual version-specific configuration directories."
                            )
                        _apply_theme_configuration(source_user_cfg, permanent_cfg, theme_config)
                    cfg_source = permanent_cfg
                    cfg_writeback_target = permanent_cfg
                else:
                    if packaged_cfg is None:
                        raise LauncherError("Theme package default .cfg was not found after extraction.")
                    permanent_cfg = _theme_user_cfg_path(str(manifest["theme_id"]))
                    permanent_cfg.parent.mkdir(parents=True, exist_ok=True)
                    if not permanent_cfg.exists():
                        shutil.copy2(packaged_cfg, permanent_cfg)
                    cfg_source = permanent_cfg
                    cfg_writeback_target = permanent_cfg

            splash_override_path = None
            splash_rel = str(manifest.get("default_splash_relpath", "") or "")
            if splash_rel:
                candidate_splash = theme_root / splash_rel
                if candidate_splash.exists() and candidate_splash.is_file():
                    splash_override_path = candidate_splash

            qss_override_path = None
            if bool(manifest.get("require_external_qss")):
                qss_override_path = external_assets.get("qss")
                if qss_override_path is None or not qss_override_path.exists() or not qss_override_path.is_file():
                    raise LauncherError("Required external style-sheet (.qss) is not available. Please download the required external assets again.")

            self._launch_with_prepared_theme(
                theme_folder=theme_root,
                cfg_source=cfg_source.resolve(),
                cfg_writeback_target=cfg_writeback_target.resolve(),
                source_label=f"Theme File: {theme_file}",
                cleanup_dir=extraction_root,
                splash_override_path=splash_override_path,
                qss_override_path=qss_override_path.resolve() if qss_override_path is not None else None,
                resolved_freecad_executable=resolved_freecad_executable,
                raw_freecad_executable_text=raw_freecad_executable_text,
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            self.append_status(f"Launch from Theme failed: {exc}")

    def copy_reload_command(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(RELOAD_CONSOLE_COMMAND)
        self.update_idletasks()
        self.append_status("Copied Python reload command to clipboard.")

    def append_status(self, text: str) -> None:
        self.status_text.configure(state="normal")
        self.status_text.insert("end", text + "\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

    def clear_status(self) -> None:
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.configure(state="disabled")

    def status(self, text: str) -> None:
        self.clear_status()
        self.append_status(text)

    def scan_theme_folder(self) -> tuple[Path | None, Path | None, Path | None, Path | None, list[str]]:
        self._collect_ui_to_settings()
        notes: list[str] = []

        folder_text = self.settings.theme_folder.strip()
        if not folder_text:
            return None, None, None, None, notes

        folder = Path(folder_text)
        if not folder.exists() or not folder.is_dir():
            return None, None, None, None, notes

        cfg_files = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".cfg"], key=lambda p: p.name.lower())
        qss_files = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".qss"], key=lambda p: p.name.lower())

        cfg_path = ThemeFolderScanner.find_cfg(folder)
        qss_path = ThemeFolderScanner.find_qss(folder)
        splash_path = ThemeFolderScanner.find_splash(folder)
        icon_theme_root = ThemeFolderScanner.find_external_icon_theme_root(folder)

        if cfg_files:
            notes.append(".cfg files in the Theme Folder are ignored. Use theme-configuration.json for theme configuration.")
        if len(qss_files) > 1 and qss_path is not None:
            notes.append(f"Multiple .qss files found. Using: {qss_path.name}")
        if self.settings.enable_external_icon_theme and icon_theme_root is None:
            notes.append("External icon theme is enabled, but no icon files were detected in the Theme Folder or in icons/ Icons/ images/ Images/.")

        return cfg_path, qss_path, splash_path, icon_theme_root, notes


    def _scan_specific_theme_folder(self, theme_folder: Path) -> tuple[Path | None, Path | None, Path | None, Path | None, list[str]]:
        notes: list[str] = []
        if not theme_folder.exists() or not theme_folder.is_dir():
            return None, None, None, None, notes
        # Creator Mode source files are top-level only. Copies/backups in subfolders
        # are intentionally ignored so there is never ambiguity about what launches.
        cfg_files = sorted([p for p in theme_folder.iterdir() if p.is_file() and p.suffix.lower() == ".cfg"], key=lambda p: p.name.lower())
        qss_files = sorted([p for p in theme_folder.iterdir() if p.is_file() and p.suffix.lower() == ".qss"], key=lambda p: p.name.lower())
        cfg_path = cfg_files[0] if len(cfg_files) == 1 else None
        qss_path = qss_files[0] if len(qss_files) == 1 else None
        splash_path = ThemeFolderScanner.find_splash(theme_folder)
        icon_theme_root = ThemeFolderScanner.find_external_icon_theme_root(theme_folder)
        if self.settings.enable_external_icon_theme and icon_theme_root is None:
            notes.append("External icon theme is enabled, but no icon files were detected in the Theme Folder or in icons/ Icons/ images/ Images/.")
        return cfg_path, qss_path, splash_path, icon_theme_root, notes

    def validate_theme_folder(self) -> tuple[bool, list[str], list[str], Path | None, Path | None, Path | None, Path | None]:
        self._collect_ui_to_settings()
        errors: list[str] = []
        warnings: list[str] = []
        exe, raw_exe_text = self._resolve_effective_freecad_executable()
        theme_folder = Path(self.settings.theme_folder).expanduser() if self.settings.theme_folder else None
        if not exe or not exe.exists():
            if raw_exe_text:
                errors.append(f"FreeCAD executable is missing or does not exist.\nConfigured path:\n{raw_exe_text}")
            else:
                errors.append("FreeCAD executable is missing or does not exist.")
        if not theme_folder:
            errors.append("Theme Folder is not selected.")
            return False, errors, warnings, None, None, None, None
        if not theme_folder.exists() or not theme_folder.is_dir():
            errors.append("Theme Folder does not exist or is not a folder.")
            return False, errors, warnings, None, None, None, None
        cfg_files = sorted([p for p in theme_folder.iterdir() if p.is_file() and p.suffix.lower() == ".cfg"], key=lambda p: p.name.lower())
        qss_files = sorted([p for p in theme_folder.iterdir() if p.is_file() and p.suffix.lower() == ".qss"], key=lambda p: p.name.lower())
        _detected_cfg, qss_path, splash_path, icon_theme_root, notes = self._scan_specific_theme_folder(theme_folder)
        warnings.extend(notes)
        if len(qss_files) != 1:
            errors.append(f"Theme Folder must contain exactly one top-level .qss file; found {len(qss_files)}. Move backup copies into a subfolder.")
        desired_cfg = str(getattr(self.settings, "creator_cfg_filename", "") or "").strip()
        cfg_path = None
        if not desired_cfg:
            errors.append("Configured .cfg filename is empty. Open Advanced and enter the Creator Mode .cfg filename.")
        elif Path(desired_cfg).name != desired_cfg or Path(desired_cfg).suffix.lower() != ".cfg":
            errors.append("Configured .cfg filename must be a filename ending in .cfg, without a folder path.")
        else:
            cfg_path = theme_folder / desired_cfg
            other_cfgs = [x for x in cfg_files if x.name.lower() != desired_cfg.lower()]
            if other_cfgs:
                names = ", ".join(x.name for x in other_cfgs)
                errors.append(
                    f"Theme Folder contains a different top-level .cfg file ({names}). "
                    f"Creator Mode is configured to use '{desired_cfg}'. Remove the old/different .cfg file from the Theme Folder or move it into a subfolder before starting FreeCAD."
                )
            elif not cfg_path.is_file():
                warnings.append(f"Configured .cfg '{desired_cfg}' does not exist yet. External Theme Creator will create it in the Theme Folder from theme-configuration.json before FreeCAD starts.")
        theme_configuration_path = theme_folder / THEME_CONFIGURATION_FILENAME
        if not theme_configuration_path.is_file():
            errors.append(f'{THEME_CONFIGURATION_FILENAME} was not found in the Theme Folder.')
        if theme_configuration_path.is_file():
            try:
                _load_theme_configuration(theme_configuration_path)
            except Exception as exc:
                errors.append(str(exc))
        return len(errors) == 0, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root

    def _require_freecad_executable_now(self) -> tuple[Path, str]:
        self._persist_path_field("freecad_executable")
        resolved_executable, raw_executable_text = self._resolve_effective_freecad_executable()
        if resolved_executable is None or not resolved_executable.exists():
            autodetected = _autodetect_freecad_executable_path()
            if autodetected is not None and autodetected.exists():
                raw_executable_text = str(autodetected)
                resolved_executable = autodetected
            else:
                visible_entry_text = self._current_entry_text("freecad_executable")
                if visible_entry_text:
                    raise LauncherError(f"FreeCAD executable is missing or does not exist.\nConfigured path:\n{visible_entry_text}")
                if raw_executable_text:
                    raise LauncherError(f"FreeCAD executable is missing or does not exist.\nConfigured path:\n{raw_executable_text}")
                raise LauncherError("FreeCAD executable is missing or does not exist. Please browse for FreeCAD.exe again.")
        self.settings.freecad_executable = raw_executable_text or str(resolved_executable)
        if self.vars.get("freecad_executable") is not None:
            try:
                self.vars["freecad_executable"].set(raw_executable_text or str(resolved_executable))
            except Exception:
                pass
        try:
            self._write_settings_file()
        except Exception:
            pass
        self._write_freecad_executable_fallback(raw_executable_text or str(resolved_executable))
        return resolved_executable, raw_executable_text or str(resolved_executable)

    def validate_clicked(self) -> None:
        ok, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root = self.validate_theme_folder()
        self.clear_status()
        self.append_status("Validation passed." if ok else "Validation failed.")
        if cfg_path:
            self.append_status(f"Detected .cfg: {cfg_path}")
        if qss_path:
            self.append_status(f"Detected .qss: {qss_path}")
        if splash_path:
            self.append_status(f"Detected splash image: {splash_path}")
        if icon_theme_root:
            self.append_status(f"Detected external icon theme root: {icon_theme_root}")
        if errors:
            self.append_status("\nErrors:")
            for item in errors:
                self.append_status(f"- {item}")
        if warnings:
            self.append_status("\nWarnings:")
            for item in warnings:
                self.append_status(f"- {item}")

    def write_reload_helper_files(self, runtime_root: Path, runtime_user_home: Path | None) -> tuple[None, None]:
        """Legacy helper artifacts are obsolete; remove previous generated copies."""
        for stale in (runtime_root / 'reload_external_icon_theme.txt',
                      (runtime_user_home / 'Macro' / 'ReloadExternalIconTheme.FCMacro') if runtime_user_home else None):
            if stale is not None:
                try: stale.unlink(missing_ok=True)
                except OSError: pass
        return None, None

    def _build_launch_command_for_theme_folder(
        self,
        theme_folder: Path,
        cfg_source: Path,
        cfg_writeback_target: Path,
        source_label: str,
        splash_override_path: Path | None = None,
        qss_override_path: Path | None = None,
        resolved_freecad_executable: Path | None = None,
        raw_freecad_executable_text: str = "",
    ) -> tuple[list[str], dict[str, str], str, Path]:
        cfg_path, qss_path, splash_path, icon_theme_root, notes = self._scan_specific_theme_folder(theme_folder)
        if not self.settings.use_external_theme_stylesheet_assets:
            qss_path = None
            splash_path = None
        if not self.settings.enable_external_icon_theme:
            icon_theme_root = None
        if self.settings.use_external_theme_stylesheet_assets and splash_override_path is not None and splash_override_path.exists() and splash_override_path.is_file():
            splash_path = splash_override_path
        if self.settings.use_external_theme_stylesheet_assets and qss_override_path is not None and qss_override_path.exists() and qss_override_path.is_file():
            qss_path = qss_override_path
        from ExternalThemeCreatorMigration import theme_runtime
        runtime_root = theme_runtime(theme_folder)
        runtime_root.mkdir(parents=True, exist_ok=True)
        # The persistent theme-specific configuration is the file FreeCAD opens
        # and saves. Do not interpose a runtime user.cfg copy: --user-cfg already
        # provides the isolation we need and FreeCAD persists changes to this file.
        active_user_cfg = cfg_source.resolve()
        runtime_qss_text = _build_runtime_stylesheet(qss_path.resolve()) if qss_path else None
        runtime_user_home: Path | None = None
        runtime_splash_paths: list[Path] = []
        runtime_splash_method = ""
        need_runtime_user_home = (
            self.settings.use_freecad_user_home
            or splash_path is not None
        )
        if need_runtime_user_home:
            runtime_user_home = runtime_root / "user_home"
            runtime_user_home.mkdir(parents=True, exist_ok=True)
            self._connect_user_workbenches(runtime_user_home)

        # v0.9.12+: avoid FreeCAD's legacy images:splash_image.png path.
        # v0.9.14+: the selected PNG is passed directly to FreeCAD without any
        # External Theme Creator scaling/resampling, so the source artwork remains unchanged.
        if runtime_user_home is not None:
            for images_dir in (
                runtime_user_home / "Gui" / "Images",
                runtime_user_home / "Gui" / "images",
                runtime_user_home / "FreeCAD" / "Gui" / "Images",
                runtime_user_home / "FreeCAD" / "Gui" / "images",
            ):
                for splash_name in ("splash_image.png", "freecadsplash.png"):
                    try:
                        stale = images_dir / splash_name
                        if stale.is_file():
                            stale.unlink()
                    except Exception:
                        pass

        helper_text_path, macro_path = self.write_reload_helper_files(runtime_root, runtime_user_home)
        runtime_startup_script_path: Path | None = None
        runtime_layout_script_path: Path | None = None
        packaged_scripts_startup_path: Path | None = None
        # This flag is specific to applying a distributable .fctheme package.
        # The Develop Theme script switch must not control packaged theme scripts.
        is_packaged_theme = source_label.startswith("Theme File:")
        resolved_freecad_executable, raw_exe_text = self._resolve_effective_freecad_executable()
        if resolved_freecad_executable is None or not resolved_freecad_executable.exists():
            if raw_exe_text:
                raise LauncherError(f"FreeCAD executable is missing or does not exist.\nConfigured path:\n{raw_exe_text}")
            raise LauncherError("FreeCAD executable is missing or does not exist.")

        runtime_splash_path: Path | None = None
        if splash_path is not None:
            runtime_splash_path, runtime_splash_method = _prepare_native_splash_asset(
                splash_path.resolve(), runtime_root
            )
            runtime_splash_paths.append(runtime_splash_path)

        config_overrides: list[str] = []
        if runtime_splash_path is not None:
            config_overrides.append("SplashScreen=" + str(runtime_splash_path.resolve()))

        cmd = [str(resolved_freecad_executable.resolve())]
        if config_overrides:
            # --set-config is multitoken; --user-cfg terminates its value list.
            cmd += ["--set-config", *config_overrides]
        cmd += ["--user-cfg", str(active_user_cfg)]
        if runtime_qss_text:
            runtime_startup_script_path = runtime_root / "apply_runtime_stylesheet.FCMacro"
            _make_startup_stylesheet_script(runtime_startup_script_path, runtime_qss_text, qss_path.resolve())
        runtime_layout_instructions = (_theme_runtime_layout_instructions(theme_folder)
                                       if self.settings.use_external_configuration else [])
        if runtime_layout_instructions:
            runtime_layout_script_path = runtime_root / "apply_runtime_ui_layout.FCMacro"
            _make_startup_layout_script(runtime_layout_script_path, runtime_layout_instructions)
        packaged_scripts_dir = theme_folder / "scripts"
        if (is_packaged_theme and packaged_scripts_dir.is_dir() and
                any(item.is_file() and item.suffix.lower() == ".py"
                    for item in packaged_scripts_dir.iterdir())):
            packaged_scripts_startup_path = runtime_root / "apply_packaged_theme_scripts.FCMacro"
            _make_packaged_theme_scripts_startup(packaged_scripts_startup_path, theme_folder)
        extra_args = self.settings.extra_cli_args.strip()
        if extra_args:
            cmd.extend(shlex.split(extra_args, posix=(platform.system().lower() != "windows")))
        if runtime_startup_script_path is not None:
            cmd.append(str(runtime_startup_script_path))
        if runtime_layout_script_path is not None:
            cmd.append(str(runtime_layout_script_path))
        if packaged_scripts_startup_path is not None:
            cmd.append(str(packaged_scripts_startup_path))
        env = os.environ.copy()
        # Do not inherit theme injection from an already-themed FreeCAD session.
        # An unchecked icon option must disable it even when restarting from NUT.
        for key in ('FREECAD_EXTERNAL_ICON_THEME',
                    'FREECAD_EXTERNAL_ICON_THEME_ENABLED',
                    'FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL'):
            env.pop(key, None)
        if runtime_user_home is None:
            env.pop('FREECAD_USER_HOME', None)
        if runtime_user_home is not None:
            env["FREECAD_USER_HOME"] = str(runtime_user_home)
        if is_packaged_theme:
            # Avoid inheriting a different Develop Theme session's script target
            # or disabled-script switch when Apply Theme starts from that session.
            env["EXTERNAL_THEME_CREATOR_THEME_FOLDER"] = str(theme_folder.resolve())
            env["EXTERNAL_THEME_CREATOR_UI_SCRIPTS_ENABLED"] = "1" if packaged_scripts_startup_path else "0"
        if self.settings.enable_external_icon_theme and icon_theme_root is not None:
            env["FREECAD_EXTERNAL_ICON_THEME"] = str(icon_theme_root.resolve())
            env["FREECAD_EXTERNAL_ICON_THEME_ENABLED"] = "1"
            env["FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL"] = "1" if self.settings.prefer_external_icons else "0"
        summary: list[str] = []
        summary.append(f"Executable: {self.settings.freecad_executable}")
        if str(resolved_freecad_executable) != str(self.settings.freecad_executable).strip():
            summary.append(f"Resolved executable: {resolved_freecad_executable}")
        summary.append(f"{source_label}: {theme_folder}")
        summary.append(f"Config source: {cfg_source.resolve()}")
        summary.append(f"Detected .qss: {qss_path.resolve()}" if qss_path else "Detected .qss: none")
        summary.append(f"Detected splash image: {splash_path.resolve()}" if splash_path else "Detected splash image: none")
        summary.append(f"Detected external icon theme root: {icon_theme_root.resolve()}" if icon_theme_root else "Detected external icon theme root: none")
        summary.append(f"Active persistent user.cfg: {active_user_cfg}")
        if runtime_user_home is not None:
            summary.append(f"FREECAD_USER_HOME={runtime_user_home}")
        if runtime_startup_script_path is not None:
            summary.append(f"Startup stylesheet script: {runtime_startup_script_path}")
        if runtime_layout_script_path is not None:
            summary.append(f"Startup semantic layout script: {runtime_layout_script_path}")
        if packaged_scripts_startup_path is not None:
            summary.append(f"Startup packaged-theme scripts: {packaged_scripts_startup_path}")
        if runtime_splash_paths:
            summary.append("Splash source passed to FreeCAD:")
            for splash_target in runtime_splash_paths:
                summary.append(f"- {splash_target}")
            if runtime_splash_method:
                summary.append(f"Splash handling: {runtime_splash_method}")
        if self.settings.enable_external_icon_theme and icon_theme_root is not None:
            summary.append(f"FREECAD_EXTERNAL_ICON_THEME={icon_theme_root.resolve()}")
            summary.append("FREECAD_EXTERNAL_ICON_THEME_ENABLED=1")
            summary.append("FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL=" + ("1" if self.settings.prefer_external_icons else "0"))
        summary.append("Config persistence: direct (FreeCAD saves the active --user-cfg file)")
        summary.append("Python console reload command:")
        summary.append(RELOAD_CONSOLE_COMMAND)
        if notes:
            summary.append("Warnings:")
            for item in notes:
                summary.append(f"- {item}")
        return cmd, env, "\n".join(summary), active_user_cfg

    def build_launch_command(self) -> tuple[list[str], dict[str, str], str]:
        self._collect_ui_to_settings()
        ok, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root = self.validate_theme_folder()
        if not ok:
            raise LauncherError("\n".join(errors))
        theme_folder = Path(self.settings.theme_folder).resolve()
        cfg_writeback_target = cfg_path.resolve() if cfg_path is not None else None
        if cfg_path is None:
            desired_cfg = str(getattr(self.settings, "creator_cfg_filename", "") or "").strip()
            if not desired_cfg:
                raise LauncherError("Configured .cfg filename is empty. Open Advanced and enter the Creator Mode .cfg filename.")
            cfg_path = (theme_folder / desired_cfg).resolve()
            cfg_writeback_target = cfg_path
        if not cfg_path.exists():
            theme_config = _load_theme_configuration(theme_folder / THEME_CONFIGURATION_FILENAME)
            source_user_cfg = self._resolve_creator_source_user_cfg()
            _apply_theme_configuration(source_user_cfg, cfg_path, theme_config)
        cmd, env, summary, runtime_user_cfg = self._build_launch_command_for_theme_folder(
            theme_folder=theme_folder,
            cfg_source=cfg_path.resolve(),
            cfg_writeback_target=cfg_writeback_target.resolve(),
            source_label="Theme Folder",
        )
        return cmd, env, summary

    def _posix_process_group_is_active(self, process_group_id: int | None) -> bool:
        if os.name == "nt" or process_group_id is None or process_group_id <= 0:
            return False
        try:
            os.killpg(process_group_id, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False

    def _wait_for_freecad_ready(self, process, timeout_seconds: float = 90.0, process_group_id: int | None = None) -> bool:
        start = time.time()
        pid = process.pid
        if os.name == "nt":
            while time.time() - start < timeout_seconds:
                if process.poll() is not None:
                    return False
                if self._windows_process_has_visible_top_level_window(pid):
                    return True
                self.update_idletasks()
                self.update()
                time.sleep(0.25)
            return False

        alive_since: float | None = None
        grace_seconds = 5.0 if _is_linux_appimage_path(self.settings.freecad_executable) else 2.0
        while time.time() - start < timeout_seconds:
            process_alive = process.poll() is None
            group_alive = self._posix_process_group_is_active(process_group_id)
            alive = process_alive or group_alive
            now = time.time()
            if alive:
                if alive_since is None:
                    alive_since = now
                elif now - alive_since >= grace_seconds:
                    return True
            else:
                if process.poll() is not None and alive_since is None:
                    return False
                alive_since = None
            self.update_idletasks()
            self.update()
            time.sleep(0.5)
        return alive_since is not None

    def _windows_process_has_visible_top_level_window(self, pid: int) -> bool:
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            found = {"visible_window": False}
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def callback(hwnd, lparam):
                window_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                if window_pid.value != pid:
                    return True
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindowTextLengthW(hwnd) <= 0:
                    return True
                found["visible_window"] = True
                return False
            user32.EnumWindows(EnumWindowsProc(callback), 0)
            return found["visible_window"]
        except Exception:
            return False

    def _spawn_post_exit_helper(self, pid: int, runtime_user_cfg: Path | None, cfg_path: Path | None, cleanup_dir: Path | None, process_group_id: int | None = None) -> None:
        runtime_user_cfg_text = str(runtime_user_cfg.resolve()) if runtime_user_cfg is not None else ""
        cfg_path_text = str(cfg_path.resolve()) if cfg_path is not None else ""
        cleanup_dir_text = str(cleanup_dir.resolve()) if cleanup_dir is not None else ""
        helper_base = Path(tempfile.gettempdir()) / f"ui_launcher_post_exit_{pid}"

        if os.name == "nt":
            def _ps_literal(value: str) -> str:
                return "'" + value.replace("'", "''") + "'"

            helper_path = helper_base.with_suffix(".ps1")
            helper_code = textwrap.dedent(
                f"""\
                $ErrorActionPreference = 'SilentlyContinue'
                $pidToWatch = {pid}
                $runtimeUserCfg = {_ps_literal(runtime_user_cfg_text)}
                $cfgPath = {_ps_literal(cfg_path_text)}
                $cleanupDir = {_ps_literal(cleanup_dir_text)}

                function Test-ProcessRunning([int]$TargetPid) {{
                    try {{
                        $null = Get-Process -Id $TargetPid -ErrorAction Stop
                        return $true
                    }} catch {{
                        return $false
                    }}
                }}

                function Test-SafeTemporaryCleanupDir([string]$PathText) {{
                    if ([string]::IsNullOrWhiteSpace($PathText)) {{
                        return $false
                    }}
                    try {{
                        $resolved = [System.IO.Path]::GetFullPath($PathText)
                        $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
                    }} catch {{
                        return $false
                    }}
                    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {{
                        return $false
                    }}
                    if ($resolved.TrimEnd('\') -eq $tempRoot.TrimEnd('\')) {{
                        return $false
                    }}
                    if (-not $resolved.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {{
                        return $false
                    }}
                    return ([System.IO.Path]::GetFileName($resolved)).StartsWith('.uix_')
                }}

                while (Test-ProcessRunning $pidToWatch) {{
                    Start-Sleep -Seconds 1
                }}

                if (-not [string]::IsNullOrWhiteSpace($runtimeUserCfg) -and -not [string]::IsNullOrWhiteSpace($cfgPath) -and (Test-Path -LiteralPath $runtimeUserCfg -PathType Leaf)) {{
                    $parent = Split-Path -Parent $cfgPath
                    if (-not [string]::IsNullOrWhiteSpace($parent)) {{
                        New-Item -ItemType Directory -Force -Path $parent | Out-Null
                    }}
                    Copy-Item -LiteralPath $runtimeUserCfg -Destination $cfgPath -Force
                }}

                if (Test-SafeTemporaryCleanupDir $cleanupDir) {{
                    Remove-Item -LiteralPath $cleanupDir -Recurse -Force -ErrorAction SilentlyContinue
                }}

                Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
                """
            )
            helper_path.write_text(helper_code, encoding="utf-8")
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(helper_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            )
            return

        def _sh_literal(value: str) -> str:
            return "'" + value.replace("'", "'\"'\"'") + "'"

        helper_path = helper_base.with_suffix(".sh")
        helper_code = textwrap.dedent(
            f"""\
            #!/bin/sh
            pid_to_watch={pid}
            runtime_user_cfg={_sh_literal(runtime_user_cfg_text)}
            cfg_path={_sh_literal(cfg_path_text)}
            cleanup_dir={_sh_literal(cleanup_dir_text)}

            process_is_running() {{
                kill -0 "$1" 2>/dev/null
            }}

            resolve_dir() {{
                if [ -n "$1" ] && [ -d "$1" ]; then
                    (cd "$1" 2>/dev/null && pwd -P)
                fi
            }}

            temp_root=$(resolve_dir "${{TMPDIR:-/tmp}}")
            cleanup_dir_resolved=$(resolve_dir "$cleanup_dir")

            is_safe_temporary_cleanup_dir() {{
                [ -n "$cleanup_dir_resolved" ] || return 1
                [ -n "$temp_root" ] || return 1
                [ "$cleanup_dir_resolved" != "$temp_root" ] || return 1
                case "$cleanup_dir_resolved" in
                    "$temp_root"/.uix_*) return 0 ;;
                    *) return 1 ;;
                esac
            }}

            while process_is_running "$pid_to_watch" || process_group_is_running "$process_group_id"; do
                sleep 1
            done

            if [ -n "$runtime_user_cfg" ] && [ -n "$cfg_path" ] && [ -f "$runtime_user_cfg" ]; then
                mkdir -p "$(dirname "$cfg_path")"
                cp -f "$runtime_user_cfg" "$cfg_path"
            fi

            if is_safe_temporary_cleanup_dir; then
                rm -rf "$cleanup_dir_resolved"
            fi

            rm -f "$0"
            """
        )
        helper_path.write_text(helper_code, encoding="utf-8")
        helper_path.chmod(0o700)
        subprocess.Popen(
            ["/bin/sh", str(helper_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    @staticmethod
    def _connect_user_workbenches(isolated_home: Path) -> None:
        """Expose installed user workbenches in a themed FreeCAD user home.

        Never copy or move workbenches. Only create links within a profile that
        ETC owns. Existing user Mod entries are always left untouched.
        """
        home = Path.home()
        system = platform.system().lower()
        if system == 'windows':
            roaming = Path(os.environ.get('APPDATA', home / 'AppData' / 'Roaming'))
            roots = [roaming / 'FreeCAD']
        elif system == 'darwin':
            roots = [home / 'Library' / 'Application Support' / 'FreeCAD',
                     home / 'Library' / 'Preferences' / 'FreeCAD',
                     home / '.local' / 'share' / 'FreeCAD']
        else:
            roots = [Path(os.environ.get('XDG_DATA_HOME', home / '.local' / 'share')) / 'FreeCAD',
                     home / '.local' / 'share' / 'FreeCAD']
        sources = []
        for root in roots:
            locations = [root]
            if root.is_dir():
                try:
                    locations.extend(child for child in root.iterdir() if child.is_dir() and
                                     child.name.startswith(('v1-', 'v0-', 'v2-')))
                except OSError:
                    pass
            for location in locations:
                mod = location / 'Mod'
                if mod.is_dir() and mod.resolve() != (isolated_home / 'Mod').resolve() and mod not in sources:
                    sources.append(mod)
        if not sources:
            return
        target = isolated_home / 'Mod'
        # Fast path for a single conventional Mod directory.
        if len(sources) == 1 and not target.exists() and not target.is_symlink():
            try:
                target.symlink_to(sources[0], target_is_directory=True)
                return
            except OSError:
                pass
        target.mkdir(parents=True, exist_ok=True)
        for source in sources:
            try:
                children = list(source.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir():
                    continue
                link = target / child.name
                if link.exists() or link.is_symlink():
                    continue
                try:
                    link.symlink_to(child, target_is_directory=True)
                except OSError:
                    # Windows users may not have permission to create symlinks.
                    # Do not copy files or modify the source workbench.
                    continue

    def _launch_with_prepared_theme(
        self,
        theme_folder: Path,
        cfg_source: Path,
        cfg_writeback_target: Path,
        source_label: str,
        cleanup_dir: Path | None = None,
        splash_override_path: Path | None = None,
        qss_override_path: Path | None = None,
        resolved_freecad_executable: Path | None = None,
        raw_freecad_executable_text: str = "",
    ) -> None:
        self.save_settings()
        cmd, env, summary, runtime_user_cfg = self._build_launch_command_for_theme_folder(
            theme_folder=theme_folder.resolve(),
            cfg_source=cfg_source.resolve(),
            cfg_writeback_target=cfg_writeback_target.resolve(),
            source_label=source_label,
            splash_override_path=splash_override_path.resolve() if splash_override_path is not None else None,
            qss_override_path=qss_override_path.resolve() if qss_override_path is not None else None,
            resolved_freecad_executable=resolved_freecad_executable.resolve() if resolved_freecad_executable is not None else None,
            raw_freecad_executable_text=raw_freecad_executable_text,
        )
        # Packaged themes use a stable profile beside their persistent CFG,
        # never the temporary extracted package's runtime directory.
        if source_label.startswith("Theme File:"):
            applied_home = cfg_source.resolve().parent / "user_home"
            applied_home.mkdir(parents=True, exist_ok=True)
            self._connect_user_workbenches(applied_home)
            env["FREECAD_USER_HOME"] = str(applied_home)
            summary += "\nApplied theme user home: " + str(applied_home)
        self.clear_status()
        self.append_status("Launching FreeCAD...\n")
        self.append_status(summary)
        self.append_status("\nCommand:")
        self.append_status(" ".join(_quote_arg(part) for part in cmd))
        # The replacement splash runs in a separate Qt process. Only suppress
        # FreeCAD's native splash if that helper has actually started.
        splash_handle = None
        suppressed_cfg = None
        splash_source = splash_override_path if splash_override_path and splash_override_path.is_file() else _find_theme_splash_png(theme_folder)
        _splash_diagnostic(theme_folder / RUNTIME_DIR_NAME,
                           'LAUNCH path=_launch_with_prepared_theme source=' + str(source_label) +
                           ' splash=' + str(splash_source) +
                           ' assets_enabled=' + str(self.settings.use_external_theme_stylesheet_assets) +
                           ' executable=' + str(cmd[0]))
        from ExternalThemeCreatorSplashControl import (_splash_preference_allows_custom,
                                               _prepare_suppressed_splash_launch,
                                               _restore_splash_preference_after_failed_launch)
        splash_allowed, splash_reason = _splash_preference_allows_custom(cfg_source)
        _splash_diagnostic(theme_folder / RUNTIME_DIR_NAME, 'Splash preference from CFG: ' + splash_reason)
        if splash_allowed and self.settings.use_external_theme_stylesheet_assets and splash_source and splash_source.is_file():
            freecad_exe = Path(cmd[0])
            splash_handle = _start_native_pixel_splash(freecad_exe, splash_source, theme_folder / RUNTIME_DIR_NAME)
            if splash_handle:
                try:
                    from ExternalThemeCreatorSplashControl import _macos_dock_icon_path
                    cmd, suppressed_cfg = _prepare_suppressed_splash_launch(
                        cmd, cfg_source, theme_folder / RUNTIME_DIR_NAME,
                        dock_icon_path=_macos_dock_icon_path(theme_folder) if sys.platform == 'darwin' else None)
                except Exception:
                    _stop_native_pixel_splash(splash_handle)
                    raise
                _splash_diagnostic(theme_folder / RUNTIME_DIR_NAME, 'MODE: External Theme Creator splash; native splash suppressed for process only')
            else:
                _splash_diagnostic(theme_folder / RUNTIME_DIR_NAME, 'MODE: FreeCAD native splash fallback')
        else:
            _splash_diagnostic(theme_folder / RUNTIME_DIR_NAME, 'Splash disabled or no themed splash; CFG left untouched')
        mac_ready = None
        if sys.platform == 'darwin':
            from ExternalThemeCreatorSplashControl import _macos_bundle_launch, _macos_dock_icon_path
            cmd, env, mac_ready = _macos_bundle_launch(
                cmd, env, theme_folder / RUNTIME_DIR_NAME,
                _macos_dock_icon_path(theme_folder))
        try:
            process = subprocess.Popen(cmd, env=env)
        except Exception:
            _stop_native_pixel_splash(splash_handle)
            _restore_splash_preference_after_failed_launch(suppressed_cfg)
            raise
        if self.settings.close_after_freecad_launch:
            self.append_status("\nWaiting for FreeCAD to finish loading before closing the launcher...")
            self.update_idletasks()
            # FreeCAD writes directly to cfg_source. The post-exit helper is now
            # needed only to remove an extracted temporary theme, if applicable.
            self._spawn_post_exit_helper(process.pid, None, None, cleanup_dir)
            if mac_ready is not None:
                from ExternalThemeCreatorSplashControl import _wait_macos_gui_ready
                ready = _wait_macos_gui_ready(process, mac_ready, pump=self.update)
            else:
                ready = self._wait_for_freecad_ready(process)
            _stop_native_pixel_splash(splash_handle)
            if ready:
                self.destroy()
                return
            raise RuntimeError("FreeCAD did not finish loading successfully before the launcher timeout.")
        self.append_status("\nFreeCAD started. Changes are saved directly to the persistent theme configuration.")
        self.update_idletasks()
        if splash_handle:
            if mac_ready is not None:
                from ExternalThemeCreatorSplashControl import _wait_macos_gui_ready
                _wait_macos_gui_ready(process, mac_ready, pump=self.update)
            else:
                self._wait_for_freecad_ready(process)
            _stop_native_pixel_splash(splash_handle)
        process.wait()
        if _safe_rmtree(cleanup_dir):
            self.append_status(f"Removed temporary extracted theme: {cleanup_dir}")

    def _freecad_console_executable(self, executable: Path) -> Path | None:
        """Return a headless FreeCAD executable when one can be identified safely."""
        executable = executable.resolve()
        system = platform.system().lower()
        candidates: list[Path] = []
        if system == "windows":
            candidates.extend([
                executable.with_name("FreeCADCmd.exe"),
                executable.with_name("freecadcmd.exe"),
            ])
        elif system == "darwin":
            # A selected .app may resolve through Contents/MacOS/FreeCAD; common
            # FreeCAD bundles also provide freecadcmd in Resources/bin.
            candidates.extend([
                executable.with_name("FreeCADCmd"),
                executable.with_name("freecadcmd"),
                executable.parent.parent / "Resources" / "bin" / "freecadcmd",
                executable.parent.parent / "Resources" / "bin" / "FreeCADCmd",
            ])
        else:
            candidates.extend([
                executable.with_name("FreeCADCmd"),
                executable.with_name("freecadcmd"),
            ])
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        return None

    def _probe_freecad_config(self, executable: Path) -> tuple[dict[str, str], str, Path | None]:
        """Read FreeCAD's configuration without opening the GUI dump-config dialog."""
        probe_executable = self._freecad_console_executable(executable)
        # On Windows the GUI executable displays --dump-config in a modal dialog,
        # so never use it as a discovery probe. On POSIX it is acceptable as a
        # fallback because stdout is normally available.
        if probe_executable is None and os.name != "nt":
            probe_executable = executable.resolve()
        if probe_executable is None:
            return {}, "Headless FreeCAD executable (FreeCADCmd) was not found.", None
        try:
            flags = 0
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                flags = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                [str(probe_executable), "--dump-config"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                timeout=15, creationflags=flags,
            )
            output = result.stdout or ""
            values: dict[str, str] = {}
            for line in output.splitlines():
                match = re.match(r"^\s*([^=:\s]+)\s*(?:=|:)\s*(.*?)\s*$", line)
                if match:
                    values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
            return values, output, probe_executable
        except Exception as exc:
            return {}, f"FreeCAD configuration probe failed: {exc}", probe_executable

    def _probe_freecad_user_cfg(self, executable: Path) -> Path | None:
        """Ask the selected FreeCAD build which user configuration it actually uses."""
        values, _output, _probe_executable = self._probe_freecad_config(executable)
        value = str(values.get("UserParameter", "") or "").strip()
        if value:
            candidate = Path(value).expanduser()
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        # Current development builds may report UserConfigPath rather than an
        # explicit UserParameter in --dump-config. user.cfg lives in that folder.
        config_dir = str(values.get("UserConfigPath", "") or "").strip()
        if config_dir:
            candidate = Path(config_dir).expanduser() / "user.cfg"
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        return None

    def _show_diagnostics_report(self, report: str) -> None:
        popup = tk.Toplevel(self)
        popup.title("Theme Configuration Diagnostics")
        popup.transient(self)
        popup.resizable(True, True)
        popup.minsize(720, 480)
        shell = ttk.Frame(popup, padding=12)
        shell.pack(fill="both", expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        text_widget = tk.Text(shell, wrap="none")
        text_widget.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(shell, orient="vertical", command=text_widget.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(shell, orient="horizontal", command=text_widget.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        text_widget.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text_widget.insert("1.0", report)
        text_widget.configure(state="disabled")
        buttons = ttk.Frame(shell)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def copy_report() -> None:
            self.clipboard_clear()
            self.clipboard_append(report)
            self.update_idletasks()

        def save_report() -> None:
            selected = filedialog.asksaveasfilename(
                title="Save diagnostic report",
                defaultextension=".txt",
                initialfile=f"UI-Launcher-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                parent=popup,
            )
            if selected:
                Path(selected).write_text(report, encoding="utf-8")

        ttk.Button(buttons, text="Copy", command=copy_report).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Save...", command=save_report).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Close", command=popup.destroy).pack(side="left")
        popup.geometry("900x650")

    def run_theme_configuration_diagnostics(self) -> None:
        """Run non-destructive diagnostics for Creator Mode configuration persistence."""
        self._persist_critical_paths()
        lines: list[str] = []
        lines.append(f"{APP_NAME} {APP_VERSION} - Theme Configuration Diagnostics")
        lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
        lines.append(f"Platform: {platform.platform()}")
        lines.append("")
        try:
            executable, raw_executable = self._require_freecad_executable_now()
            lines.append(f"Selected FreeCAD executable: {raw_executable}")
            lines.append(f"Resolved FreeCAD executable: {executable}")
            values, probe_output, probe_executable = self._probe_freecad_config(executable)
            lines.append(f"Configuration probe executable: {probe_executable or 'not found'}")
            for key in ("ExeVersion", "BuildVersionMajor", "BuildVersionMinor", "BuildVersionPoint", "BuildVersionSuffix", "UserParameter", "UserConfigPath", "UserAppData", "UserHomePath", "UserMacroPath"):
                if key in values:
                    lines.append(f"FreeCAD {key}: {values[key]}")
            lines.append(f"Inherited FREECAD_USER_HOME: {os.environ.get('FREECAD_USER_HOME', '<not set>')}")
            lines.append(f"Runtime FREECAD_USER_HOME option: {'enabled' if self.settings.use_freecad_user_home else 'disabled'}")
            lines.append("")

            source_cfg = self._probe_freecad_user_cfg(executable)
            if source_cfg is None:
                saved = str(getattr(self.settings, "creator_user_cfg", "") or "").strip()
                existing = [p for p in _freecad_user_cfg_candidates(saved) if p.exists() and p.is_file()]
                source_cfg = existing[0].resolve() if existing else None
            lines.append(f"Discovered normal user.cfg: {source_cfg or 'NOT FOUND'}")

            def file_status(label: str, path: Path | None) -> None:
                lines.append(f"{label}: {path or 'not available'}")
                if path is None:
                    return
                lines.append(f"  exists={path.exists()} file={path.is_file() if path.exists() else False}")
                lines.append(f"  readable={os.access(path, os.R_OK) if path.exists() else False} writable={os.access(path, os.W_OK) if path.exists() else False}")
                if path.exists() and path.is_file():
                    stat = path.stat()
                    lines.append(f"  size={stat.st_size} modified={datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}")
                    lock_candidates = [Path(str(path) + ".lock"), path.with_suffix(path.suffix + ".lock"), path.parent / (path.name + "-lock")]
                    found_locks = [str(item) for item in lock_candidates if item.exists()]
                    lines.append(f"  nearby lock candidates={'; '.join(found_locks) if found_locks else 'none'}")

            file_status("Normal configuration", source_cfg)

            theme_folder_text = str(self.settings.theme_folder or "").strip()
            theme_folder = Path(theme_folder_text).expanduser().resolve() if theme_folder_text else None
            theme_config_path = theme_folder / THEME_CONFIGURATION_FILENAME if theme_folder else None
            creator_cfg: Path | None = None
            if theme_config_path is not None and theme_config_path.exists():
                try:
                    theme_config = _load_theme_configuration(theme_config_path)
                    detected_cfg = ThemeFolderScanner.find_cfg(theme_folder) if theme_folder is not None else None
                    creator_cfg = detected_cfg.resolve() if detected_cfg is not None else (theme_folder / str(theme_config["output"]["filename"])).resolve()
                except Exception as exc:
                    lines.append(f"theme-configuration.json error: {exc}")
            lines.append("")
            lines.append(f"Theme Folder: {theme_folder or 'not selected'}")
            lines.append(f"theme-configuration.json: {theme_config_path or 'not available'}")
            file_status("Creator Theme Folder configuration", creator_cfg)

            if theme_folder is not None and creator_cfg is not None and creator_cfg.exists():
                try:
                    cmd, env, summary, runtime_cfg = self._build_launch_command_for_theme_folder(
                        theme_folder=theme_folder, cfg_source=creator_cfg, cfg_writeback_target=creator_cfg,
                        source_label="Diagnostic Creator Theme Folder", resolved_freecad_executable=executable,
                        raw_freecad_executable_text=raw_executable,
                    )
                    lines.append("")
                    lines.append("Normal Creator launch command:")
                    lines.append("  " + " ".join(_quote_arg(part) for part in cmd))
                    lines.append(f"Runtime user.cfg: {runtime_cfg}")
                    lines.append(f"Runtime FREECAD_USER_HOME: {env.get('FREECAD_USER_HOME', '<not set>')}")
                except Exception as exc:
                    lines.append(f"Could not build Creator launch command: {exc}")

            # Controlled FreeCAD write test: work only on a temporary copy.
            lines.append("")
            lines.append("Controlled FreeCAD write test (temporary copy only):")
            console_exe = self._freecad_console_executable(executable)
            test_source = preview_cfg if preview_cfg is not None and preview_cfg.exists() else source_cfg
            if console_exe is None:
                lines.append("  SKIPPED: FreeCADCmd/freecadcmd was not found.")
            elif test_source is None or not test_source.exists():
                lines.append("  SKIPPED: no source configuration was available to copy.")
            else:
                with tempfile.TemporaryDirectory(prefix="ui_launcher_cfg_diag_") as tmp_text:
                    tmp = Path(tmp_text)
                    test_cfg = tmp / "diagnostic-user.cfg"
                    shutil.copy2(test_source, test_cfg)
                    token = secrets.token_hex(8)
                    script = tmp / "write_test.py"
                    script.write_text(
                        "import FreeCAD as App\n"
                        "p = App.ParamGet('User parameter:BaseApp/Preferences/ExternalThemeCreatorDiagnostic')\n"
                        f"p.SetString('WriteTest', {token!r})\n"
                        "App.saveParameter()\n",
                        encoding="utf-8",
                    )
                    before = test_cfg.read_bytes()
                    log_path = tmp / "FreeCAD-diagnostic.log"
                    test_cmd = [str(console_exe), "--user-cfg", str(test_cfg), "--log-file", str(log_path), str(script)]
                    lines.append("  Command: " + " ".join(_quote_arg(part) for part in test_cmd))
                    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                    try:
                        result = subprocess.run(test_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30, creationflags=flags)
                        after = test_cfg.read_bytes()
                        changed = before != after
                        contains_token = token.encode("utf-8") in after
                        lines.append(f"  Exit code: {result.returncode}")
                        lines.append(f"  File changed: {changed}")
                        lines.append(f"  Diagnostic token persisted: {contains_token}")
                        lines.append(f"  Result: {'PASS' if changed and contains_token else 'FAIL'}")
                        output = (result.stdout or "").strip()
                        if output:
                            lines.append("  FreeCADCmd output (last 20 lines):")
                            for item in output.splitlines()[-20:]:
                                lines.append("    " + item)
                        if log_path.exists():
                            log_text = log_path.read_text(encoding="utf-8", errors="replace")
                            interesting = [item for item in log_text.splitlines() if re.search(r"cfg|config|parameter|lock|write|save|error|warn", item, re.I)]
                            if interesting:
                                lines.append("  Relevant log lines (last 30):")
                                for item in interesting[-30:]:
                                    lines.append("    " + item)
                    except Exception as exc:
                        lines.append(f"  ERROR: {exc}")

            if probe_output and probe_output.startswith("FreeCAD configuration probe failed"):
                lines.append("")
                lines.append(probe_output)
        except Exception as exc:
            lines.append("")
            lines.append(f"DIAGNOSTIC ERROR: {exc}")

        report = "\n".join(lines)
        self._show_diagnostics_report(report)

    def _resolve_creator_source_user_cfg(self, freecad_executable: Path | None = None) -> Path:
        """Find Creator Mode's source user.cfg, or let the creator select it."""
        saved = str(getattr(self.settings, "creator_user_cfg", "") or "").strip()

        # Prefer the selected FreeCAD build's own resolved configuration path.
        if freecad_executable is not None:
            probed = self._probe_freecad_user_cfg(freecad_executable)
            if probed is not None:
                self.settings.creator_user_cfg = str(probed)
                try:
                    self._write_settings_file()
                except Exception:
                    pass
                return probed

        existing = [p for p in _freecad_user_cfg_candidates(saved) if p.exists() and p.is_file()]
        # If several version-scoped configs exist, prefer the most recently modified.
        if existing:
            if saved:
                saved_key = os.path.normcase(os.path.abspath(str(Path(saved).expanduser())))
                for candidate in existing:
                    if os.path.normcase(os.path.abspath(str(candidate))) == saved_key:
                        return candidate.resolve()
            existing.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            resolved = existing[0].resolve()
            self.settings.creator_user_cfg = str(resolved)
            try:
                self._write_settings_file()
            except Exception:
                pass
            return resolved

        for candidate in _freecad_user_cfg_candidates(saved):
            if candidate.exists() and candidate.is_file():
                resolved = candidate.resolve()
                if str(resolved) != saved:
                    self.settings.creator_user_cfg = str(resolved)
                    try:
                        self._write_settings_file()
                    except Exception:
                        pass
                return resolved

        initialdir = str(Path(saved).expanduser().parent) if saved else str(_default_freecad_user_cfg_path().parent)
        selected = filedialog.askopenfilename(
            title="Locate FreeCAD user.cfg",
            initialdir=initialdir,
            filetypes=[("FreeCAD configuration", "*.cfg"), ("All files", "*.*")],
            parent=self,
        )
        if not selected:
            raise LauncherError(
                "FreeCAD's user.cfg could not be located automatically. "
                "Select the user.cfg used by this FreeCAD installation to continue."
            )
        selected_path = Path(selected).expanduser()
        if not selected_path.exists() or not selected_path.is_file():
            raise LauncherError("The selected FreeCAD user.cfg does not exist or is not a file.")
        resolved = selected_path.resolve()
        self.settings.creator_user_cfg = str(resolved)
        try:
            self._write_settings_file()
        except Exception:
            pass
        return resolved

    def launch_freecad(self) -> None:
        self._persist_critical_paths()
        try:
            resolved_freecad_executable, raw_freecad_executable_text = self._require_freecad_executable_now()
            ok, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root = self.validate_theme_folder()
            if not ok:
                raise LauncherError("\n".join(errors) or "Theme Folder validation failed.")

            theme_folder = Path(self.settings.theme_folder).resolve()
            theme_config = _load_theme_configuration(theme_folder / THEME_CONFIGURATION_FILENAME)

            # Creator Mode uses the configured Theme Folder .cfg as the live
            # persistent FreeCAD configuration. Existing files are never rebuilt
            # on launch. If the configured file is absent, initialize that exact
            # filename from the normal FreeCAD user.cfg using theme-configuration.json.
            if cfg_path is not None:
                active_cfg = cfg_path.resolve()
            else:
                desired_cfg = str(getattr(self.settings, "creator_cfg_filename", "") or "").strip()
                if not desired_cfg:
                    raise LauncherError("Configured .cfg filename is empty. Open Advanced and enter the Creator Mode .cfg filename.")
                active_cfg = (theme_folder / desired_cfg).resolve()
            if not active_cfg.exists():
                source_user_cfg = self._resolve_creator_source_user_cfg(resolved_freecad_executable)
                _apply_theme_configuration(source_user_cfg, active_cfg, theme_config)

            self._launch_with_prepared_theme(
                theme_folder=theme_folder,
                cfg_source=active_cfg,
                cfg_writeback_target=active_cfg,
                source_label="Theme Folder",
                resolved_freecad_executable=resolved_freecad_executable,
                raw_freecad_executable_text=raw_freecad_executable_text,
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            self.append_status(f"\nLaunch failed:\n{exc}")


    def _resolve_theme_source_for_shortcut(self, mode: str) -> tuple[Path | None, str]:
        if mode == "creator":
            folder_text = self.settings.theme_folder.strip()
            if not folder_text:
                return None, "Theme Folder is not selected."
            folder = Path(folder_text).expanduser()
            if not folder.exists() or not folder.is_dir():
                return None, "Theme Folder does not exist or is not a folder."
            return folder, ""

        theme_text = self.settings.theme_file.strip()
        if not theme_text:
            return None, "Theme is not selected."
        theme_file = Path(theme_text).expanduser()
        if not theme_file.exists() or not theme_file.is_file():
            return None, "Theme does not exist or is not a file."
        return theme_file, ""

    def _extract_theme_for_shortcut(self, theme_file: Path) -> tuple[Path, Path]:
        manifest, public_pem, signature_b64, payload_enc = self._read_theme_package(theme_file)
        self._validate_theme_manifest(manifest)
        _verify_signature(manifest, public_pem, signature_b64)
        extraction_root, theme_root = self._extract_theme_payload(manifest, payload_enc)
        return extraction_root, theme_root

    def _resolve_shortcut_icon_for_source(self, source_path: Path) -> tuple[Path | None, Path | None]:
        cleanup_dir = None
        theme_root = source_path
        if source_path.is_file() and source_path.suffix.lower() == THEME_PACKAGE_EXTENSION:
            cleanup_dir, theme_root = self._extract_theme_for_shortcut(source_path)

        theme_icon_folder = theme_root / "shortcut-icon"
        theme_icon_name = "Custom_Icon" + _platform_shortcut_icon_suffix()
        icon_path = theme_icon_folder / theme_icon_name
        if not icon_path.is_file():
            icon_path = None
        if icon_path is not None and icon_path.exists():
            return icon_path, cleanup_dir

        default_icons_dir = self.base_dir / DEFAULT_SHORTCUT_ICONS_DIR_NAME
        fallback_icon = None
        if default_icons_dir.exists() and default_icons_dir.is_dir():
            fallback_icon = _find_platform_shortcut_icon_in_folder(default_icons_dir)

        return fallback_icon, cleanup_dir



    def _shortcut_target_and_args(self, mode: str) -> tuple[Path, list[str]]:
        mode_arg = "--launch-as-user" if mode == "user" else "--launch-as-creator"
        if _is_frozen_app():
            system = platform.system().lower()
            if system == "linux":
                appimage_path = os.environ.get("APPIMAGE", "").strip()
                if appimage_path:
                    return Path(appimage_path).resolve(), [mode_arg]
            if system == "darwin":
                app_bundle = _current_macos_app_bundle()
                if app_bundle is not None:
                    return app_bundle, [mode_arg]
            return self.launcher_entry_path, [mode_arg]
        return Path(sys.executable).resolve(), [str(_launcher_entry_path()), mode_arg]

    def _create_windows_shortcut(self, shortcut_path: Path, target_path: Path, arguments: list[str], icon_path: Path | None) -> None:
        persistent_icon_path = _make_shortcut_icon_persistent(shortcut_path, icon_path)
        arg_string = subprocess.list2cmdline(arguments) if arguments else ""
        script = textwrap.dedent(f"""\
            $WshShell = New-Object -ComObject WScript.Shell
            $Shortcut = $WshShell.CreateShortcut({str(shortcut_path)!r})
            $Shortcut.TargetPath = {str(target_path)!r}
            $Shortcut.WorkingDirectory = {str(target_path.parent)!r}
            {f"$Shortcut.Arguments = {arg_string!r}" if arg_string else ""}
            {f"$Shortcut.IconLocation = {str(persistent_icon_path)!r}" if persistent_icon_path is not None else ""}
            $Shortcut.Save()
        """)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _create_macos_shortcut(self, shortcut_path: Path, target_path: Path, arguments: list[str], icon_path: Path | None, macos_splash_spec: dict | None = None) -> None:
        persistent_icon_path = _make_shortcut_icon_persistent(shortcut_path, icon_path)
        app_dir = shortcut_path
        contents = app_dir / "Contents"
        macos_dir = contents / "MacOS"
        resources_dir = contents / "Resources"
        macos_dir.mkdir(parents=True, exist_ok=True)
        resources_dir.mkdir(parents=True, exist_ok=True)

        launcher_script = macos_dir / shortcut_path.stem
        if target_path.suffix.lower() == ".app":
            command_parts = ["/usr/bin/open", "-n", str(target_path), "--args", *arguments]
            working_dir = target_path.parent
        else:
            command_parts = [str(target_path)] + arguments
            working_dir = target_path.parent
        if target_path == Path('/usr/bin/open') and arguments[:2] == ['-n', '-a']:
            # A direct Develop Theme shortcut launches the actual FreeCAD.app
            # through Launch Services; it does not read the protected folder
            # using a standalone Python subprocess. Keep a small error log for
            # broken FreeCAD app paths or failed Launch Services requests.
            log_path = _app_config_base_dir() / 'MacShortcuts' / 'develop-shortcut-direct.log'
            log_path.parent.mkdir(parents=True, exist_ok=True)
            error_alert = shlex.quote(
                'display alert "External Theme Creator" message '
                '"FreeCAD did not launch. See the Develop Theme shortcut log in Application Support." as critical'
            )
            launcher_text = (
                '#!/bin/sh\n'
                f'cd {shlex.quote(str(working_dir))} || exit 1\n'
                f'echo "$(date): Launching direct FreeCAD.app shortcut" >> {shlex.quote(str(log_path))}\n'
                f'{_shell_join(command_parts)} >> {shlex.quote(str(log_path))} 2>&1\n'
                'status="$?"\n'
                'if [ "$status" -ne 0 ]; then\n'
                f'  /usr/bin/osascript -e {error_alert} >/dev/null 2>&1 || true\n'
                'fi\n'
                'exit "$status"\n'
            )
            if macos_splash_spec:
                # Keep the splash's source PNG in Application Support rather
                # than opening the privacy-protected development folder from
                # Finder. Use FreeCAD's own Python/PySide6 to match Restart's
                # exact pixel-ratio behavior, and close at GUI readiness.
                spec = macos_splash_spec
                q = shlex.quote
                splash_python = q(spec['python'])
                splash_helper = q(spec['helper'])
                splash_image = q(spec['image'])
                splash_ready = q(spec['ready'])
                splash_dir = q(spec['directory'])
                plugin_dir = spec.get('plugin_directory') or ''
                plugin_prefix = (
                    'QT_QPA_PLATFORM_PLUGIN_PATH=' + q(plugin_dir) + ' '
                    + 'QT_PLUGIN_PATH=' + q(str(Path(plugin_dir).parent)) + ' '
                    if plugin_dir else ''
                )
                launcher_text = (
                    '#!/bin/sh\n'
                    f'cd {q(str(working_dir))} || exit 1\n'
                    f'mkdir -p {splash_dir}\n'
                    f'rm -f {splash_ready}\n'
                    f'splash_stop={q(spec["directory"] + "/splash_stop_")}$$.flag\n'
                    'rm -f "$splash_stop" "$splash_stop.ready"\n'
                    f'{plugin_prefix}{splash_python} {splash_helper} {splash_image} "$splash_stop" >> {q(str(log_path))} 2>&1 &\n'
                    'splash_pid=$!\n'
                    # Wait briefly for Qt to paint the correctly sized splash.
                    'i=0\n'
                    'while [ ! -f "$splash_stop.ready" ] && kill -0 "$splash_pid" 2>/dev/null && [ "$i" -lt 28 ]; do\n'
                    '  sleep 0.25; i=$((i+1))\n'
                    'done\n'
                    f'echo "$(date): Launching direct FreeCAD.app shortcut" >> {q(str(log_path))}\n'
                    f'{_shell_join(command_parts)} >> {q(str(log_path))} 2>&1\n'
                    'status="$?"\n'
                    'if [ "$status" -eq 0 ]; then\n'
                    '  i=0\n'
                    f'  while [ ! -f {splash_ready} ] && [ "$i" -lt 140 ]; do\n'
                    '    sleep 0.25; i=$((i+1))\n'
                    '  done\n'
                    'else\n'
                    f'  /usr/bin/osascript -e {error_alert} >/dev/null 2>&1 || true\n'
                    'fi\n'
                    'touch "$splash_stop"\n'
                    # macOS Qt sometimes leaves a helper alive after the stop
                    # marker is seen; bound shutdown instead of waiting forever.
                    'i=0\n'
                    'while kill -0 "$splash_pid" 2>/dev/null && [ "$i" -lt 12 ]; do\n'
                    '  sleep 0.25; i=$((i+1))\n'
                    'done\n'
                    'if kill -0 "$splash_pid" 2>/dev/null; then\n'
                    '  kill "$splash_pid" 2>/dev/null || true\n'
                    '  sleep 0.5\n'
                    '  kill -9 "$splash_pid" 2>/dev/null || true\n'
                    'fi\n'
                    'wait "$splash_pid" 2>/dev/null || true\n'
                    'rm -f "$splash_stop" "$splash_stop.ready"\n'
                    'exit "$status"\n'
                )
        elif '--launch-macos-creator-shortcut' in arguments:
            # Finder does not show the stderr of a bundled Python interpreter.
            # Persist its entire launch output even if Python cannot import
            # the ETC runtime (too early for its own diagnostics to run).
            log_path = _app_config_base_dir() / 'MacShortcuts' / 'develop-shortcut-process.log'
            log_path.parent.mkdir(parents=True, exist_ok=True)
            launcher_text = (
                "#!/bin/sh\n"
                f'cd {shlex.quote(str(working_dir))} || exit 1\n'
                f'echo "$(date): Launching Develop Theme shortcut" >> {shlex.quote(str(log_path))}\n'
                f'{_shell_join(command_parts)} >> {shlex.quote(str(log_path))} 2>&1\n'
                'exit "$?"\n'
            )
        else:
            launcher_text = (
                "#!/bin/sh\n"
                f'cd {shlex.quote(str(working_dir))} || exit 1\n'
                f'exec {_shell_join(command_parts)}\n'
            )
        launcher_script.write_text(launcher_text, encoding="utf-8")
        os.chmod(launcher_script, 0o755)

        icon_file_name = ""
        if persistent_icon_path is not None and persistent_icon_path.exists():
            icon_file_name = "shortcut.icns"
            shutil.copy2(persistent_icon_path, resources_dir / icon_file_name)

        icon_plist_block = ""
        if icon_file_name:
            icon_plist_block = f"    <key>CFBundleIconFile</key>\n    <string>{icon_file_name}</string>\n"

        info_plist = contents / "Info.plist"
        from xml.sax.saxutils import escape as xml_escape
        bundle_slug = (_slugify_theme_id(shortcut_path.stem).replace('_', '-') or 'freecad')[:52]
        bundle_key = hashlib.sha256(str(shortcut_path.resolve()).encode('utf-8')).hexdigest()[:10]
        plist_text = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
            "<plist version=\"1.0\">\n"
            "<dict>\n"
            f"    <key>CFBundleDisplayName</key>\n    <string>{xml_escape(shortcut_path.stem)}</string>\n"
            f"    <key>CFBundleExecutable</key>\n    <string>{xml_escape(shortcut_path.stem)}</string>\n"
            f"    <key>CFBundleIdentifier</key>\n    <string>com.externalthemecreator.shortcut.{bundle_slug}.{bundle_key}</string>\n"
            f"    <key>CFBundleName</key>\n    <string>{xml_escape(shortcut_path.stem)}</string>\n"
            "    <key>CFBundlePackageType</key>\n    <string>APPL</string>\n"
            f"{icon_plist_block}"
            "</dict>\n"
            "</plist>\n"
        )
        info_plist.write_text(plist_text, encoding="utf-8")

        codesign_path = Path("/usr/bin/codesign")
        if codesign_path.exists():
            try:
                subprocess.run(
                    [str(codesign_path), "--force", "--deep", "--sign", "-", str(app_dir)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    def _create_linux_shortcut(self, shortcut_path: Path, target_path: Path, arguments: list[str], icon_path: Path | None) -> None:
        exec_parts = [_desktop_exec_escape(str(target_path))] + [_desktop_exec_escape(part) for part in arguments]
        persistent_icon_path = _make_shortcut_icon_persistent(shortcut_path, icon_path)
        desktop_text = f"""[Desktop Entry]
Type=Application
Version=1.0
Name={_desktop_file_escape(shortcut_path.stem)}
Exec={' '.join(exec_parts)}
Path={str(target_path.parent)}
Terminal=false
"""
        if persistent_icon_path is not None and persistent_icon_path.exists():
            desktop_text += f"Icon={str(persistent_icon_path)}\n"
        desktop_text += "Categories=Graphics;Engineering;\n"
        shortcut_path.write_text(desktop_text, encoding="utf-8")
        _mark_linux_shortcut_trusted(shortcut_path, persistent_icon_path)

    def create_shortcut_clicked(self) -> None:
        self._persist_critical_paths()
        self._collect_ui_to_settings()
        self.save_settings()
        default_location = str(Path.home() / "Desktop")
        dialog = CreateShortcutDialog(self, default_name="FreeCAD", default_location=default_location)
        self.wait_window(dialog)
        if not dialog.result:
            return

        mode = dialog.result["mode"]
        source_path, error = self._resolve_theme_source_for_shortcut(mode)
        if source_path is None:
            messagebox.showerror(APP_NAME, error)
            return

        target_path, shortcut_arguments = self._shortcut_target_and_args(mode)
        if not target_path.exists():
            messagebox.showerror(APP_NAME, f"Launcher target was not found:\n{target_path}")
            return

        location_path = Path(dialog.result["location"]).expanduser()
        if not location_path.exists() or not location_path.is_dir():
            messagebox.showerror(APP_NAME, "Shortcut Location does not exist or is not a folder.")
            return

        cleanup_dir = None
        try:
            icon_path, cleanup_dir = self._resolve_shortcut_icon_for_source(source_path)
            system = platform.system().lower()
            name = dialog.result["name"].strip()
            if system == "windows":
                shortcut_path = location_path / f"{name}.lnk"
                self._create_windows_shortcut(shortcut_path, target_path, shortcut_arguments, icon_path)
            elif system == "darwin":
                shortcut_path = location_path / f"{name}.app"
                self._create_macos_shortcut(shortcut_path, target_path, shortcut_arguments, icon_path)
            else:
                shortcut_path = location_path / f"{name}.desktop"
                self._create_linux_shortcut(shortcut_path, target_path, shortcut_arguments, icon_path)
            messagebox.showinfo(APP_NAME, f"Shortcut created successfully:\n{shortcut_path}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
        finally:
            _safe_rmtree(cleanup_dir)

    def refresh_status(self) -> None:
        self._refresh_selected_theme_metadata()
        ok, errors, warnings, cfg_path, qss_path, splash_path, icon_theme_root = self.validate_theme_folder()
        self.clear_status()
        self.append_status("Ready" if ok else "Needs attention")
        self.append_status("")
        self.append_status(f"Theme file: {self.settings.theme_file}" if self.settings.theme_file else "Theme file: none")
        self.append_status(f"Author Key: {self.settings.author_key_file}" if self.settings.author_key_file else "Author Key: none")
        self.append_status(f"Detected .cfg: {cfg_path}" if cfg_path else "Detected .cfg: none")
        self.append_status(f"Detected .qss: {qss_path}" if qss_path else "Detected .qss: none")
        self.append_status(f"Detected splash image: {splash_path}" if splash_path else "Detected splash image: none")
        self.append_status(f"Detected external icon theme root: {icon_theme_root}" if icon_theme_root else "Detected external icon theme root: none")
        self.append_status("")
        if errors:
            self.append_status("Errors:")
            for item in errors:
                self.append_status(f"- {item}")
            self.append_status("")
        if warnings:
            self.append_status("Warnings:")
            for item in warnings:
                self.append_status(f"- {item}")
            self.append_status("")


def _quote_arg(value: str) -> str:
    if not value:
        return '""'
    escaped = value.replace('"', '\\"')
    if any(ch.isspace() for ch in value) or any(ch in value for ch in '"\''):
        return f'"{escaped}"'
    return value




def _load_saved_settings_for_headless_launch() -> AppSettings:
    settings_candidates: list[Path] = []
    primary_settings_path = _settings_storage_path(_resource_base_dir())
    executable_fallback_path = _freecad_executable_fallback_path(_resource_base_dir())
    settings_candidates.append(primary_settings_path)

    legacy_local_settings_path = Path(__file__).resolve().parent / SETTINGS_FILE
    if legacy_local_settings_path not in settings_candidates:
        settings_candidates.append(legacy_local_settings_path)

    for settings_path in settings_candidates:
        if settings_path.exists():
            try:
                return _load_app_settings_from_path(settings_path)
            except Exception as exc:
                raise LauncherError(f"Could not read saved settings:\n{exc}") from exc

    return AppSettings()


def _show_headless_error(message: str) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def _shortcut_launch_diagnostic(message: str, theme_folder=None) -> None:
    """Log shortcut launch failures only."""
    if not any(token in str(message).upper() for token in ('ERROR', 'FALLBACK', 'FAILED')):
        return
    try:
        from datetime import datetime
        shared = Path(os.environ.get('APPDATA', str(Path.home()))) / 'External Theme Creator' / 'shortcut-splash.log' if os.name == 'nt' else Path.home() / '.ui-launcher' / 'shortcut-splash.log'
        destinations = [shared]
        if theme_folder:
            destinations.append(Path(theme_folder) / RUNTIME_DIR_NAME / 'splash-startup.log')
        for path in destinations:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('a', encoding='utf-8') as out:
                    out.write(datetime.now().isoformat(timespec='seconds') + ' SHORTCUT ' + str(message) + '\n')
            except OSError: pass
    except Exception: pass


def _launch_freecad_without_ui(mode: str) -> int:
    app = None
    destroyed = False
    try:
        _shortcut_launch_diagnostic('ENTRY mode=' + str(mode) + ' launcher=' + str(Path(__file__).resolve()) + ' python=' + str(sys.executable))
        settings = _load_saved_settings_for_headless_launch()
        _shortcut_launch_diagnostic('Settings loaded; creator_folder=' + str(settings.theme_folder) + '; splash_assets_enabled=' + str(settings.use_external_theme_stylesheet_assets))
        freecad_executable = str(settings.freecad_executable).strip()
        if not freecad_executable:
            raise LauncherError("Saved setting 'FreeCAD executable' is empty.")

        app = ThemeLauncherApp()
        app.withdraw()

        app.vars["freecad_executable"].set(freecad_executable)

        if mode == "user":
            theme_file = str(settings.theme_file).strip()
            if not theme_file:
                raise LauncherError("Saved setting 'Theme' is empty.")
            theme_path = Path(theme_file).expanduser()
            if not theme_path.exists() or not theme_path.is_file():
                raise LauncherError(f"Saved Theme was not found:\n{theme_path}")
            app.vars["user_mode"].set(True)
            app.vars["creator_mode"].set(False)
            app.vars["theme_file"].set(str(theme_path))
            app._collect_ui_to_settings()
            _shortcut_launch_diagnostic('Dispatch applied-theme launch')
            app.launch_from_theme_clicked()
        elif mode == "creator":
            theme_folder = str(settings.theme_folder).strip()
            if not theme_folder:
                raise LauncherError("Saved setting 'Theme Folder' is empty.")
            theme_folder_path = Path(theme_folder).expanduser()
            if not theme_folder_path.exists() or not theme_folder_path.is_dir():
                raise LauncherError(f"Saved Theme Folder was not found:\n{theme_folder_path}")
            app.vars["user_mode"].set(False)
            app.vars["creator_mode"].set(True)
            app.vars["theme_folder"].set(str(theme_folder_path))
            app._collect_ui_to_settings()
            _shortcut_launch_diagnostic('Dispatch creator launch; splash=' + str(_find_theme_splash_png(theme_folder_path)), theme_folder_path)
            app.launch_freecad()
            _shortcut_launch_diagnostic('Creator launch returned', theme_folder_path)
        else:
            raise LauncherError(f"Unsupported launch mode: {mode}")

        try:
            app.update_idletasks()
        except Exception:
            pass

        try:
            exists = bool(int(app.winfo_exists()))
        except Exception:
            exists = False

        if exists:
            try:
                app.destroy()
            except Exception:
                pass
        else:
            destroyed = True

        return 0
    except Exception as exc:
        if app is not None and not destroyed:
            try:
                exists = bool(int(app.winfo_exists()))
            except Exception:
                exists = False
            if exists:
                try:
                    app.destroy()
                except Exception:
                    pass
        _shortcut_launch_diagnostic('ERROR ' + type(exc).__name__ + ': ' + str(exc))
        _show_headless_error(str(exc))
        return 1




def _read_theme_package_metadata(theme_file: Path) -> dict[str, str]:
    empty = {
        "copyright": "",
        "license_terms": "",
        "license_notice_brief": "",
        "license_notice": "",
        "license": "",
        "license_text": "",
        "theme_package": THEME_PACKAGE_MODE_COMPLETE,
        "require_external_cfg": "0",
        "external_cfg_url": "",
        "external_cfg_filename": "",
        "require_external_qss": "0",
        "external_qss_url": "",
        "external_qss_filename": "",
        "theme_id": "",
    }
    try:
        with zipfile.ZipFile(theme_file, "r") as outer_zip:
            if "manifest.json" not in outer_zip.namelist():
                return empty
            manifest = json.loads(outer_zip.read("manifest.json").decode("utf-8"))
            license_text = ""
            if "payload.enc" in outer_zip.namelist():
                try:
                    payload_bytes = _decrypt_payload(outer_zip.read("payload.enc"))
                    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as payload_zip:
                        payload_names = set(payload_zip.namelist())
                        for candidate_name in (f'files/{THEME_LICENSE_RELPATH}', THEME_LICENSE_RELPATH, LICENSE_FILE_NAME, f"files/{LICENSE_FILE_NAME}"):
                            if candidate_name in payload_names:
                                license_text = payload_zip.read(candidate_name).decode("utf-8", errors="replace")
                                break
                except Exception:
                    license_text = ""
        return {
            "copyright": str(manifest.get("copyright", "") or ""),
            "license_terms": str(manifest.get("license_terms", "") or ""),
            "license_notice_brief": str(manifest.get("license_notice_brief", "") or ""),
            "license_notice": str(manifest.get("license_notice", "") or ""),
            "license": str(manifest.get("license", "") or ""),
            "license_text": str(license_text or ""),
            "theme_package": str(manifest.get("theme_package", THEME_PACKAGE_MODE_COMPLETE) or THEME_PACKAGE_MODE_COMPLETE),
            "require_external_cfg": "1" if bool(manifest.get("require_external_cfg")) else "0",
            "external_cfg_url": str(manifest.get("external_cfg_url", "") or ""),
            "external_cfg_filename": str(manifest.get("external_cfg_filename", "") or ""),
            "require_external_qss": "1" if bool(manifest.get("require_external_qss")) else "0",
            "external_qss_url": str(manifest.get("external_qss_url", "") or ""),
            "external_qss_filename": str(manifest.get("external_qss_filename", "") or ""),
            "theme_id": str(manifest.get("theme_id", "") or ""),
        }
    except Exception:
        return empty

def main() -> int:
    try:
        args = sys.argv[1:]
        if "--launch-as-user" in args:
            return _launch_freecad_without_ui("user")
        if "--launch-as-creator" in args:
            return _launch_freecad_without_ui("creator")
        app = ThemeLauncherApp()
        app.mainloop()
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
