"""External Theme Creator UI Inspector: read-only Qt/FreeCAD interface examination.

Capture with a customizable shortcut while hovering a widget.
No persistent Qt styles, palettes, settings or FreeCAD preferences are modified.
"""
from __future__ import annotations
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets, QtNetwork

_CONTROLLER = None
_DEFAULT_SHORTCUT = 'Ctrl+Shift+I'
_SETTINGS_PATH = 'User parameter:BaseApp/Preferences/Mod/ExternalThemeCreator/UIInspector'


def _saved_shortcut():
    try:
        value = App.ParamGet(_SETTINGS_PATH).GetString('CaptureShortcut', _DEFAULT_SHORTCUT)
        if value and not QtGui.QKeySequence(value).isEmpty():
            return value
    except Exception:
        pass
    return _DEFAULT_SHORTCUT


def _key_combo(event):
    key = event.key()
    if key in (QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift, QtCore.Qt.Key_Alt,
               QtCore.Qt.Key_Meta, QtCore.Qt.Key_AltGr):
        return ''
    if key == QtCore.Qt.Key_unknown:
        return ''
    try:
        sequence = QtGui.QKeySequence(event.modifiers() | key)
        return sequence.toString(QtGui.QKeySequence.PortableText)
    except (TypeError, ValueError):
        try:
            sequence = QtGui.QKeySequence(int(event.modifiers()) | int(key))
            return sequence.toString(QtGui.QKeySequence.PortableText)
        except Exception:
            return ''


class ShortcutRecorder(QtWidgets.QKeySequenceEdit):
    """Native Qt shortcut recorder. Key combinations are captured by Qt itself."""
    shortcutRecorded = QtCore.Signal(str)
    recordingFocusChanged = QtCore.Signal(bool)

    def __init__(self, initial, parent=None):
        super().__init__(parent)
        self.setKeySequence(QtGui.QKeySequence(initial))
        self.setToolTip('Click here, then press the desired keyboard shortcut. Tab moves focus.')
        self.setMinimumWidth(170)
        self.setMaximumWidth(260)
        self.keySequenceChanged.connect(self._save)

    def focusInEvent(self, event):
        self.recordingFocusChanged.emit(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.recordingFocusChanged.emit(False)

    def _save(self):
        shortcut = self.keySequence().toString(QtGui.QKeySequence.PortableText)
        if shortcut:
            self.shortcutRecorded.emit(shortcut)


class ReportPanel(QtWidgets.QScrollArea):
    """Readable alternating-row report with bold labels and selectable values."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.content = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout(self.content)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(0)
        self.setWidget(self.content)
        self.raw_text = ''
        self.set_report('Ready to capture a FreeCAD element.')

    def set_report(self, raw):
        self.raw_text = str(raw or '')
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        # Explicit colors rather than palette AlternateBase (often identical under FreeCAD QSS).
        # Match the CFG Instructions editor rather than the FreeCAD application
        # palette: NUT may report a dark Base even in its light dialogs.
        row_colors = ('#e3e3e3', '#f1f1f1')
        color_pattern = re.compile(r'(?<![\w#])#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?(?![0-9a-fA-F])')
        index = 0
        for line in self.raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('===') and line.endswith('==='):
                header = QtWidgets.QLabel(line.strip('= ').title())
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                header.setStyleSheet('QLabel { color: #202020; background: transparent; }')
                header.setContentsMargins(5, 13, 5, 5)
                self.layout.addWidget(header)
                continue
            row = QtWidgets.QWidget()
            row.setObjectName('TCInspectorReportRow')
            row.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            row.setStyleSheet('QWidget#TCInspectorReportRow { background-color: %s; border: none; border-radius: 0px; }' % row_colors[index % 2])
            holder = QtWidgets.QHBoxLayout(row)
            holder.setContentsMargins(12, 8, 12, 8)
            holder.setSpacing(12)
            # Only interpret a colon as key/value when it looks like a field.
            if ': ' in line and not line.startswith(('http:', 'https:')):
                key, value = line.split(': ', 1)
                keylabel = QtWidgets.QLabel(key + ':')
                keyfont = keylabel.font()
                keyfont.setBold(True)
                keylabel.setFont(keyfont)
                keylabel.setStyleSheet('QLabel { color: #202020; background: transparent; border: none; }')
                keylabel.setMinimumWidth(165)
                keylabel.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                valuelabel = QtWidgets.QLabel(value or '—')
                valuelabel.setWordWrap(True)
                valuelabel.setStyleSheet('QLabel { color: #202020; background: transparent; border: none; }')
                valuelabel.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                holder.addWidget(keylabel, 0)
                holder.addWidget(valuelabel, 1)
                color_match = color_pattern.search(value)
                if color_match:
                    color_value = color_match.group(0)[:7]
                    swatch = QtWidgets.QLabel()
                    swatch.setFixedSize(20, 20)
                    swatch.setToolTip(color_value)
                    swatch.setStyleSheet('QLabel { background-color: %s; border: 1px solid #777777; border-radius: 3px; }' % color_value)
                    holder.addSpacing(6)
                    holder.addWidget(swatch, 0, QtCore.Qt.AlignTop)
            else:
                value = QtWidgets.QLabel(line)
                value.setWordWrap(True)
                value.setStyleSheet('QLabel { color: #202020; background: transparent; border: none; }')
                value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                holder.addWidget(value)
            self.layout.addWidget(row)
            index += 1
        self.layout.addStretch(1)


def _split_reports(detail):
    """Separate action information without losing widget/model/hierarchy fields."""
    widget_lines = []
    action_lines = []
    in_action = False
    for line in detail.splitlines():
        if line.strip() == '=== ACTION ===':
            in_action = True
            action_lines.append(line)
            continue
        if line.startswith('==='):
            in_action = False
        (action_lines if in_action else widget_lines).append(line)
    if not action_lines:
        action_lines = ['No QAction associated with the element under the pointer.']
    return '\n'.join(widget_lines), '\n'.join(action_lines)


def _safe(f, fallback=''):
    try:
        return f()
    except Exception:
        return fallback


def _text(v):
    try:
        return str(v)
    except Exception:
        return '<unavailable>'


def _theme_folder():
    try:
        import ExternalThemeCreatorCommands as tc
        d = tc._load_runtime_settings()
        raw = d.get('theme_folder') or tc.params().GetString(tc.FOLDER_KEY, '')
        return Path(raw).expanduser() if raw else None
    except Exception:
        return None


def _sources(widget):
    """Conservative source assessment, not an assertion of Qt's computed cascade."""
    folder = _theme_folder()
    app = QtWidgets.QApplication.instance()
    sheet = _safe(lambda: app.styleSheet(), '') or ''
    object_name = _safe(widget.objectName, '')
    class_name = _safe(lambda: widget.metaObject().className(), '')
    qt_name = type(widget).__name__
    local = _safe(widget.styleSheet, '') or ''
    # Qt does not expose the computed QSS rule; selector text is a candidate only.
    candidate_selectors = [s for s in ('#' + object_name if object_name else '', class_name, qt_name) if s]
    matches = []
    for sel in candidate_selectors:
        if re.search(re.escape(sel) + r'\s*(?=[{,:\[\s])', sheet):
            matches.append(sel)
    qss_path = ''
    if folder and folder.is_dir():
        candidates = sorted(folder.glob('*.qss'))
        if candidates:
            qss_path = _text(candidates[0])
    if local.strip():
        qss_status = 'Confirmed: widget has a local stylesheet'
    elif sheet.strip() and matches:
        qss_status = 'Possible: matching selector text found (cascade unverified)'
    elif sheet.strip():
        qss_status = 'Unknown: application QSS active; inherited, parent and generic rules may apply'
    else:
        qss_status = 'No application-level QSS detected; default or other style sources possible'
    cfg = folder / 'theme-configuration.json' if folder else None
    info = ['QSS: ' + qss_status, 'Application stylesheet active: ' + str(bool(sheet.strip())),
            'Widget-local stylesheet active: ' + str(bool(local.strip())),
            'Potential selectors: ' + (', '.join(matches) or 'None found'),
            'Development QSS candidate: ' + (qss_path or 'Not found')]
    if cfg and cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding='utf-8-sig'))
            ui = data.get('ui', {}) if isinstance(data, dict) else {}
            count = sum(len(x) for x in ui.values() if isinstance(x, list)) if isinstance(ui, dict) else 0
            info.extend(['Configuration: theme-configuration.json exists (' + str(count) + ' instructions)',
                         'CFG/JSON status of this widget: Unknown; FreeCAD parameters do not expose widget-to-preference provenance.'])
        except Exception as exc:
            info.append('Configuration: JSON could not be inspected: ' + _text(exc))
    else:
        info.append('Configuration: no development theme-configuration.json found; widget provenance unknown')
    info.append('IMPORTANT: Absence of a matching selector does NOT prove the FreeCAD default is in use.')
    return '\n'.join(info)


def _model_details(view, global_pos):
    viewport = view.viewport()
    point = viewport.mapFromGlobal(global_pos)
    index = _safe(lambda: view.indexAt(point), QtCore.QModelIndex())
    if not index.isValid():
        return 'Item under pointer: None'
    model = view.model()
    lines = ['Index row/column: %d / %d' % (index.row(), index.column())]
    for role, name in [(QtCore.Qt.DisplayRole, 'DisplayRole'), (QtCore.Qt.ToolTipRole, 'ToolTipRole'),
                       (QtCore.Qt.DecorationRole, 'DecorationRole'), (QtCore.Qt.CheckStateRole, 'CheckStateRole'),
                       (QtCore.Qt.UserRole, 'UserRole')]:
        value = _safe(lambda r=role: model.data(index, r), None)
        if isinstance(value, QtGui.QIcon):
            value = 'QIcon (null=%s, cacheKey=%s)' % (value.isNull(), value.cacheKey())
        if value is not None:
            lines.append('%s: %s' % (name, _text(value)[:400]))
    return '\n'.join(lines)


def _find_view(widget):
    obj = widget
    for _ in range(12):
        if obj is None:
            break
        if isinstance(obj, QtWidgets.QAbstractItemView):
            return obj
        obj = _safe(obj.parentWidget, None)
    return None


def _find_action(widget, pos):
    obj = widget
    for _ in range(8):
        if obj is None:
            break
        if isinstance(obj, QtWidgets.QToolButton):
            action = _safe(obj.defaultAction, None)
            if action:
                return action
        if isinstance(obj, (QtWidgets.QMenu, QtWidgets.QMenuBar)):
            action = _safe(lambda: obj.actionAt(obj.mapFromGlobal(pos)), None)
            if action:
                return action
        obj = _safe(obj.parentWidget, None)
    return None




def _toolbutton_context(widget, pos):
    """Return the captured split button, displayed action, and recursive menu actions.

    Works for FreeCAD composite toolbar commands in any workbench, without
    hardcoded Sketcher or PartDesign action names.
    """
    button = widget
    for _ in range(9):
        if isinstance(button, QtWidgets.QToolButton):
            break
        button = _safe(button.parentWidget, None) if button is not None else None
    if not isinstance(button, QtWidgets.QToolButton):
        return None, None, []
    default = _safe(button.defaultAction, None)
    menus = []
    menu = _safe(button.menu, None)
    if menu is not None:
        menus.append(menu)
    if default is not None:
        menu = _safe(default.menu, None)
        if menu is not None:
            menus.append(menu)
    for action in _safe(button.actions, []) or []:
        menu = _safe(action.menu, None)
        if menu is not None:
            menus.append(menu)
    results, visited = [], set()
    def traverse(menu, depth=0):
        if menu is None or id(menu) in visited or depth > 8 or len(results) >= 180:
            return
        visited.add(id(menu))
        for entry in _safe(menu.actions, []) or []:
            if len(results) >= 180:
                return
            results.append((entry, depth))
            traverse(_safe(entry.menu, None), depth + 1)
    for menu in menus:
        traverse(menu)
    return button, default, results


def _dropdown_action_lines(widget, pos):
    """Report actual QAction entries, including nested menus and per-action icons."""
    button, default, entries = _toolbutton_context(widget, pos)
    if button is None or not entries:
        return []
    lines = ['=== DROPDOWN ACTIONS ===', 'Menu entries: %d' % len(entries)]
    if default is not None:
        lines.append('Toolbar default command: ' + (_freecad_command_id(default) or '(unavailable)'))
    shown = _safe(button.icon, None)
    shown_fp = _image_fingerprint(shown, 32) if shown is not None and not shown.isNull() else None
    for i, (action, depth) in enumerate(entries[:120], 1):
        if _safe(action.isSeparator, False):
            lines.append('%d. [Separator]' % i)
            continue
        title = str(_safe(action.text, '') or '').replace('&', '').strip()
        command = _freecad_command_id(action) or _tooltip_command_id(_safe(action.toolTip, ''))
        icon = _safe(action.icon, None)
        label = '%d. %s%s' % (i, '  ' * depth, title or '(untitled)')
        if command:
            label += ' | ' + command
        if icon is not None and not icon.isNull():
            icon_fp = _image_fingerprint(icon, 32)
            if shown_fp is not None and icon_fp == shown_fp:
                label += ' | Displayed on toolbar'
            resolved = _resolve_action_icon(action, icon, visual_fallback=False)
            label += ' | Icon: ' + (_format_icon_file_result(resolved) if resolved else 'Unknown (source unavailable)')
        else:
            label += ' | Icon: None'
        lines.append(label)
    if len(entries) > 120:
        lines.append('... %d additional entries omitted' % (len(entries) - 120))
    return lines


def _resolve_action_icon(action, icon, visual_fallback=True, progress=None):
    """Shared action resolver for toolbar buttons, menus and nested QAction entries.

    Exact resource/file metadata is preferred; filename-based candidates are
    labeled, and rendered comparisons do not claim provenance.
    """
    if icon is None or icon.isNull():
        return ''
    result = (_action_icon_metadata(action) or
              _icon_command_candidate(action) or
              _resource_command_candidate(action) or
              _universal_resource_candidate(action, icon) or
              _mapped_resource_candidate(action, icon) or
              _mod_command_icon_candidate(action, icon))
    if result:
        return result
    if visual_fallback:
        return _visual_icon_match(icon, progress=progress)
    return ''


def _action_icon_metadata(action):
    """Return an icon location only when QAction/Qt actually provides it."""
    for prop in ('iconFile', 'iconPath', 'iconSource', 'iconName'):
        value = _safe(lambda n=prop: action.property(n), None)
        if isinstance(value, str) and value.strip():
            path = value.strip()
            if path.startswith((':/', 'qrc:/')) or Path(path).is_file():
                return path
    icon = _safe(action.icon, None)
    name = _safe(icon.name, '') if icon is not None else ''
    return (str(name) + ' (Qt icon-theme name; source path unavailable)') if name else ''


# A QIcon generally does not retain its input filename. Compare its rendered
# pixels with actual files or accessible Qt resources when metadata is absent.
# These are *visual matches*, not evidence of the original loading path.
_ICON_EXTENSIONS = {'.svg', '.png', '.xpm', '.ico'}

# Verified FreeCAD core-command resource mappings. These identifiers can differ
# significantly from command names. Source: src/Gui/CommandStructure.cpp.
_CORE_COMMAND_ICON_NAMES = {
    'Std_Part': ('Geofeaturegroup',),
    'Std_Group': ('folder',),
    'Std_VarSet': ('VarSet',),
    # Verified src/Gui/CommandView.cpp Draw Style QAction registrations.
    'Std_DrawStyleAsIs': ('DrawStyleAsIs',),
    'Std_DrawStylePoints': ('DrawStylePoints',),
    'Std_DrawStyleWireframe': ('DrawStyleWireFrame',),
    'Std_DrawStyleHiddenLine': ('DrawStyleHiddenLine',),
    'Std_DrawStyleNoShading': ('DrawStyleNoShading',),
    'Std_DrawStyleShaded': ('DrawStyleShaded',),
    'Std_DrawStyleFlatLines': ('DrawStyleFlatLines',),
}


def _format_icon_file_result(result):
    """Keep the filename first and retain the confidence annotation."""
    result = str(result or '')
    if not result or result.startswith(('Unknown', 'None detected')):
        return result
    # Preserve Qt resource descriptions already beginning with their basename.
    if result.startswith(':/') or result.startswith('qrc:/'):
        return result.rsplit('/', 1)[-1].split(' (', 1)[0] + ' — ' + result
    match = re.match(r'^(.*?\.(?:svg|png|xpm|ico))(?=\s*\(|$)(.*)$', result, re.I)
    if not match:
        return result
    path, note = match.groups()
    name = path.replace('\\', '/').rsplit('/', 1)[-1]
    if path == name:
        return result
    return name + ' — ' + path + note


def _mapped_resource_candidate(action, icon):
    """Check verified source mappings against active external theme or installed icons.

    Icon source is still a *candidate* unless its rendered bytes match.
    """
    cmd = _freecad_command_id(action)
    keys = _CORE_COMMAND_ICON_NAMES.get(cmd, ())
    if not keys:
        return ''
    roots = []
    active = _active_icon_root()
    if active:
        roots.append(active)
    folder = _theme_folder()
    if folder:
        roots.append(folder / 'icons')
    roots.extend(_mod_icon_roots())
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for name in keys:
            for ext in ('.svg', '.png', '.xpm', '.ico'):
                # Prefer the theme root, then recurse for installed Mod icons.
                candidates = [root / (name + ext)]
                if root in _mod_icon_roots():
                    candidates += list(root.rglob(name + ext))[:5]
                for path in candidates:
                    if not path.is_file():
                        continue
                    fingerprint = _image_fingerprint(icon, 32)
                    if fingerprint is not None and fingerprint == _image_fingerprint(QtGui.QIcon(str(path)), 32):
                        return str(path.resolve()) + ' (FreeCAD source mapping; visual match, loaded source unverified)'
                    return str(path.resolve()) + ' (FreeCAD source mapping; visual match not confirmed)'
    return keys[0] + '.svg (FreeCAD source resource name; path unavailable; actual extension unverified)'



def _mod_icon_roots():
    """Icon trees in FreeCAD's installed and per-user Mod directories.

    Include the running ETC module itself. This discovery is read-only and does
    not depend on which workbench or external theme is currently active.
    """
    roots = []
    try:
        home = Path(App.getHomePath()).resolve()
        roots.extend((home / 'Mod', home / 'data' / 'Mod',
                      home / 'data' / 'Gui', home / 'share' / 'FreeCAD' / 'Mod',
                      home / 'share' / 'FreeCAD' / 'Gui',
                      home / 'Resources' / 'icons'))
    except Exception:
        pass
    try:
        user = Path(App.getUserAppDataDir()).resolve()
        roots.extend((user / 'Mod', user / 'data' / 'Mod'))
    except Exception:
        pass
    roots.append(Path(__file__).resolve().parent / 'Resources' / 'icons')
    # Deduplicate overlapping roots, including a workbench inside system Mod.
    return tuple(dict.fromkeys(p for p in roots if p.is_dir()))


@lru_cache(maxsize=4)
def _installed_mod_icon_files(roots):
    result = []
    for root_name in roots:
        root = Path(root_name)
        try:
            for path in root.rglob('*'):
                if path.is_file() and path.suffix.lower() in _ICON_EXTENSIONS:
                    result.append(str(path))
        except (OSError, PermissionError):
            continue
    return tuple(dict.fromkeys(result))


def _mod_command_icon_candidate(action, icon, command_override=''):
    """Identify exact icon filenames from FreeCAD Mod trees where possible.

    A pixel match verifies the *artwork*, not the native action's loading path.
    Filename candidates are clearly labeled if FreeCAD does not expose a path.
    """
    command = command_override or _freecad_command_id(action)
    if not command or icon is None or icon.isNull():
        return ''
    roots = tuple(str(x) for x in _mod_icon_roots())
    files = _installed_mod_icon_files(roots)
    aliases = {
        'ExternalThemeCreator_Inspector': ('ETC_inspector',),
        'ExternalThemeCreator_Apply': ('ETC_apply',),
        'ExternalThemeCreator_Develop': ('ETC_develop',),
        'ExternalThemeCreator_CFG': ('ETC_cfg',),
        'ExternalThemeCreator_Export': ('ETC_export',),
        'ExternalThemeCreator_ReloadQSS': ('ETC_reload_QSS',),
        'ExternalThemeCreator_ReloadIcons': ('ETC_reload_icons',),
    }
    names = {command, command.replace('_', '-'), command.replace('_', ''),
             command.split('_', 1)[-1]}
    names.update(aliases.get(command, ()))
    names.update(_CORE_COMMAND_ICON_NAMES.get(command, ()))
    wanted = {_normalized_icon_stem(name) for name in names}
    candidates = [f for f in files if _normalized_icon_stem(Path(f).stem) in wanted]
    if not candidates:
        return ''
    displayed32 = _image_fingerprint(icon, 32)
    displayed24 = _image_fingerprint(icon, 24)
    for filename in candidates:
        trial = QtGui.QIcon(filename)
        if (displayed32 is not None and displayed24 is not None
                and _image_fingerprint(trial, 32) == displayed32
                and _image_fingerprint(trial, 24) == displayed24):
            return filename + ' (installed Mod icon visual match; original source unverified)'
    if len(candidates) == 1:
        return candidates[0] + ' (installed Mod command-name candidate; visual match not confirmed)'
    return ', '.join(Path(f).name for f in candidates[:5]) + ' (multiple installed Mod candidates; source unverified)'


def _image_fingerprint(icon, side):
    if icon is None:
        return None
    try:
        pixmap = icon.pixmap(side, side)
        if pixmap.isNull():
            return None
        image = pixmap.toImage().convertToFormat(QtGui.QImage.Format_RGBA8888)
        return (image.width(), image.height(), bytes(image.constBits()))
    except Exception:
        return None


@lru_cache(maxsize=8)
def _icon_search_candidates(theme_dir, freecad_dir):
    candidates = []
    if theme_dir:
        folder = Path(theme_dir) / 'icons'
        if folder.is_dir():
            for path in folder.rglob('*'):
                if path.is_file() and path.suffix.lower() in _ICON_EXTENSIONS:
                    candidates.append(str(path))
                    if len(candidates) >= 1500:
                        break
    # FreeCAD's Qt resource filesystem contains paths for many compiled icons.
    # Browsing it is supported by Qt; no executable or resource files are edited.
    pending = [':/']
    visited = set()
    resource_count = 0
    while pending and resource_count < 16000:
        directory = pending.pop()
        if directory in visited:
            continue
        visited.add(directory)
        qdir = QtCore.QDir(directory)
        try:
            entries = qdir.entryInfoList(QtCore.QDir.AllEntries | QtCore.QDir.NoDotAndDotDot)
        except Exception:
            continue
        for entry in entries:
            name = entry.fileName()
            full = (directory.rstrip('/') + '/' + name)
            if entry.isDir():
                pending.append(full)
            elif Path(name).suffix.lower() in _ICON_EXTENSIONS:
                candidates.append(full)
                resource_count += 1
                if resource_count >= 16000:
                    break
    # Include installed and user addons, including ETC's Resources/icons.
    for candidate in _installed_mod_icon_files(tuple(str(x) for x in _mod_icon_roots())):
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _visual_icon_match(icon, progress=None):
    # Two sizes drastically reduce accidental matches caused by icon scaling.
    reference = [_image_fingerprint(icon, side) for side in (24, 32)]
    if any(value is None for value in reference):
        return ''
    folder = _theme_folder()
    try:
        freecad = App.getHomePath()
    except Exception:
        freecad = ''
    active_root = _active_icon_root()
    candidates = list(_icon_search_candidates(str(folder) if folder else '', str(freecad)))
    if active_root is not None:
        # Prioritize icons actually supplied to this FreeCAD session.
        for candidate in reversed(list(active_root.rglob('*'))):
            if candidate.is_file() and candidate.suffix.lower() in _ICON_EXTENSIONS:
                item = str(candidate)
                if item in candidates:
                    candidates.remove(item)
                candidates.insert(0, item)
    found = []
    total = max(1, len(candidates))
    for n, source in enumerate(candidates):
        if progress and n % 24 == 0:
            progress(35 + int(60 * n / total))
        trial = QtGui.QIcon(source)
        if trial.isNull():
            continue
        if _image_fingerprint(trial, 32) != reference[1]:
            continue
        if _image_fingerprint(trial, 24) == reference[0]:
            found.append(source)
            if len(found) >= 3:
                break
    if len(found) == 1:
        src = found[0]
        return src + ' (visual match; original source unverified)'
    if found:
        return ', '.join(Path(src).name for src in found) + ' (multiple visual matches; source unverified)'
    return ''


def _active_icon_root():
    """Read the launch-time icon root, not only External Theme Creator's saved folder."""
    value = os.environ.get('FREECAD_EXTERNAL_ICON_THEME', '').strip()
    if value and os.environ.get('FREECAD_EXTERNAL_ICON_THEME_ENABLED', '1').strip().lower() not in ('0', 'false', 'no', 'off'):
        path = Path(value).expanduser()
        if path.is_dir():
            return path
    return None


def _freecad_command_id(action):
    """Use explicit QAction metadata, followed by FreeCAD's tooltip command line."""
    if action is None:
        return ''
    for value in (_safe(action.objectName, ''), _safe(action.data, '')):
        value = str(value or '').strip()
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+', value):
            return value
    tooltip = str(_safe(action.toolTip, '') or '')
    # FreeCAD tooltip markup typically ends with an italic command identifier.
    matches = re.findall(r'\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b', tooltip)
    return matches[-1] if matches else ''


def _tooltip_command_id(tooltip):
    """Sketcher can expose the command ID only in the QToolButton tooltip."""
    text = re.sub(r'<[^>]+>', ' ', str(tooltip or ''))
    hits = re.findall(r'\b(?:Sketcher|SketcherGui|Std|PartDesign)_[A-Za-z0-9_]+\b', text)
    return hits[-1] if hits else ''


def _icon_command_candidate(action):
    """Resolve the active-theme icon from QAction command metadata.

    This is a *candidate*, because FreeCAD does not expose the actual QIcon
    backing filename. Report it as such, never as a verified visual match.
    """
    if action is None:
        return ''
    root = _active_icon_root()
    if root is None:
        folder = _theme_folder()
        if folder and (folder / 'icons').is_dir():
            root = folder / 'icons'
    if root is None:
        return ''
    try:
        import ExternalThemeCreatorCommands as tc
        keys = tc._action_icon_candidates(action)
        command_id = _freecad_command_id(action)
        if command_id:
            keys = [tc._normalize_icon_key(command_id)] + [tc._normalize_icon_key(x) for x in _CORE_COMMAND_ICON_NAMES.get(command_id, ())] + keys
        index = tc._icon_index(root)
        match = tc._find_icon_for_keys(index, keys)
        if match:
            return str(match.resolve()) + ' (command-name match; source unverified)'
    except Exception:
        pass
    return ''


def _normalized_icon_stem(value):
    """Normalize separators and case, without guessing icon file extensions."""
    return re.sub(r'[^a-z0-9]', '', str(value).lower())


@lru_cache(maxsize=4)
def _registered_resource_name_index(theme_dir, freecad_dir):
    """Index *accessible* icon resources once for all QAction types/workbenches."""
    index = {}
    for source in _icon_search_candidates(theme_dir, freecad_dir):
        stem = _normalized_icon_stem(Path(source.replace('\\', '/')).stem)
        if stem:
            index.setdefault(stem, []).append(source)
    return index


def _universal_resource_candidate(action, icon, command_override=''):
    """Resolve icon names independent of QAction type or owning workbench.

    A FreeCAD C++ action group may use a resource basename different from its
    QAction command ID. Index registered resources, then verify against the
    actual QAction or toolbar pixmap whenever possible. Never claim filename
    provenance merely because a name happens to match.
    """
    command = command_override or _freecad_command_id(action)
    if not command or icon is None or icon.isNull():
        return ''
    try:
        home = str(App.getHomePath())
    except Exception:
        home = ''
    folder = _theme_folder()
    sources = _registered_resource_name_index(str(folder) if folder else '', home)
    stems = [command, command.replace('_', ''), command.split('_', 1)[-1]]
    stems.extend(_CORE_COMMAND_ICON_NAMES.get(command, ()))
    # FreeCAD compiled resources commonly omit the leading command namespace.
    # These are only candidates; never label them confirmed without a visual match.
    for prefix in ('Sketcher_', 'PartDesign_', 'Std_'):
        if command.startswith(prefix):
            stems.append(command[len(prefix):])
    paths = []
    for stem in stems:
        paths.extend(sources.get(_normalized_icon_stem(stem), ()))
    paths = list(dict.fromkeys(paths))
    if not paths:
        return ''
    expected = _image_fingerprint(icon, 32)
    for source in paths:
        trial = QtGui.QIcon(source)
        if not trial.isNull() and expected is not None and _image_fingerprint(trial, 32) == expected:
            if _image_fingerprint(trial, 24) == _image_fingerprint(icon, 24):
                return source + ' (command/resource name and visual match; original loading path unverified)'
    if len(paths) == 1:
        return paths[0] + ' (command/resource-name candidate; visual match not confirmed)'
    return ', '.join(Path(x).name for x in paths[:5]) + ' (multiple resource-name candidates; unverified)'


def _resource_command_candidate(action):
    """Look for an exact command-named icon in registered Qt resources."""
    command = _freecad_command_id(action)
    if not command:
        return ''
    names = (command, command.replace('_', '-')) + _CORE_COMMAND_ICON_NAMES.get(command, ())
    roots = (':/icons', ':/ui', ':/FreeCAD', ':/')
    for root in roots:
        for base in names:
            for ext in ('.svg', '.png', '.xpm'):
                path = root.rstrip('/') + '/' + base + ext
                if QtCore.QFile.exists(path):
                    return base + ext + ' (Qt resource candidate: ' + path + ')'
    return ''


def _github_command_lookup(action):
    """Provide a targeted source-search URL, not an unverified icon filename.

    GitHub's code search cannot be queried anonymously via its REST code-search
    endpoint, so the browser search is a transparent manual fallback.
    """
    command = _freecad_command_id(action)
    if not command:
        return ''
    from urllib.parse import quote
    return ('https://github.com/search?q=' +
            quote('repo:FreeCAD/FreeCAD "' + command + '"') + '&type=code')


def _sketcher_resource_icon_candidate(widget, action, icon):
    """Resolve a *real* resource/file by the captured Sketcher command.

    Some Sketcher split buttons expose the displayed command only in the
    QToolButton tooltip.  Search the full discovered Qt resource tree instead
    of guessing one resource prefix.  Never invent an extension or path.
    """
    tooltip_command = _tooltip_command_id(_safe(widget.toolTip, ''))
    action_command = _freecad_command_id(action)
    command = tooltip_command or action_command
    if not command.startswith('Sketcher_'):
        return ''
    names = {command.lower(), command.replace('_', '-').lower()}
    # These forms are used by historical Sketcher resources and aliases.
    if command == 'Sketcher_CreateSlot':
        names.add('sketcher_createslot')
    try:
        home = str(App.getHomePath())
    except Exception:
        home = ''
    theme_folder = _theme_folder()
    candidates = _icon_search_candidates(str(theme_folder) if theme_folder else '', home)
    matches = [source for source in candidates
               if Path(source.replace('\\', '/')).stem.lower() in names]
    if not matches:
        return ''
    # The button may show a different icon than its menu's default QAction.
    # Compare the actual painted icon first, avoiding false attribution.
    visible_icon = _safe(widget.icon, None) if isinstance(widget, QtWidgets.QAbstractButton) else None
    if visible_icon is None or visible_icon.isNull():
        visible_icon = icon
    reference = _image_fingerprint(visible_icon, 32)
    for source in matches:
        if reference is not None and _image_fingerprint(QtGui.QIcon(source), 32) == reference:
            return source + ' (Sketcher command-name and visual match; original loading path unverified)'
    if len(matches) == 1:
        return matches[0] + ' (Sketcher command-name candidate; visual match not confirmed)'
    return ', '.join(Path(x).name for x in matches[:5]) + ' (multiple Sketcher command-name candidates; source unverified)'


def _icon_file(widget, action, view, pos, progress=None):
    """Report an icon's source only when Qt metadata or a file proves it.

    QIcon.pixmap() and cacheKey() cannot recover a source pathname. In
    particular, a resource or compiled icon must not be named by guessing
    from its tooltip or command title.
    """
    icon = None
    # Toolbar split buttons can paint an icon different from their default
    # QAction. Inspect the visible button image first, including its arrow side.
    button, _default, _menu_actions = _toolbutton_context(widget, pos)
    if button is not None:
        icon = _safe(button.icon, None)
    elif isinstance(widget, QtWidgets.QAbstractButton):
        icon = _safe(widget.icon, None)
    if (icon is None or icon.isNull()) and action is not None:
        icon = _safe(action.icon, None)
    if (icon is None or icon.isNull()) and view is not None:
        idx = _safe(lambda: view.indexAt(view.viewport().mapFromGlobal(pos)), QtCore.QModelIndex())
        if idx.isValid():
            value = _safe(lambda: idx.data(QtCore.Qt.DecorationRole), None)
            if isinstance(value, QtGui.QIcon):
                icon = value
            elif isinstance(value, QtGui.QPixmap):
                return 'Unknown (model supplies a QPixmap without source metadata)'
    if icon is None or icon.isNull():
        return 'None detected'

    # Some actions or widgets retain an explicit icon location as metadata.
    # Do not infer source from QIcon cache keys or raster data.
    candidates = []
    for obj in (action, widget):
        if obj is None:
            continue
        for prop in ('iconFile', 'iconPath', 'iconSource', 'iconName'):
            value = _safe(lambda o=obj, n=prop: o.property(n), None)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
    # QIcon.name is available for theme icons (not arbitrary file-backed icons).
    name = _safe(icon.name, '') or ''
    if name:
        candidates.append(name)

    known_dirs = []
    folder = _theme_folder()
    active_root = _active_icon_root()
    if active_root:
        known_dirs.append(active_root)
    if folder:
        known_dirs.append(folder / 'icons')
    known_dirs.extend(_mod_icon_roots())

    for candidate in candidates:
        if candidate.startswith(':/') or candidate.startswith('qrc:/'):
            # Qt resources live inside compiled modules or registered qrc bundles.
            return candidate.rsplit('/', 1)[-1] + ' (Qt resource: ' + candidate + ')'
        path = Path(candidate)
        if path.is_file():
            return str(path.resolve())
        for directory in known_dirs:
            target = directory / candidate
            if target.is_file():
                return str(target.resolve())
        # Resource names or themed icon names can be reported, not asserted as paths.
        if path.suffix.lower() in ('.svg', '.png', '.ico', '.xpm'):
            return path.name + ' (source location not available)'
        if name and candidate == name:
            return name + ' (Qt icon-theme name; source location not available)'

    # For a composite FreeCAD command, resolve the menu action whose actual
    # icon is currently painted on the toolbar. The default action can differ.
    if button is not None and _menu_actions:
        actual = _image_fingerprint(icon, 32)
        if actual is not None:
            for candidate_action, _depth in _menu_actions:
                candidate_icon = _safe(candidate_action.icon, None)
                if candidate_icon is not None and not candidate_icon.isNull() and _image_fingerprint(candidate_icon, 32) == actual:
                    resolved = _resolve_action_icon(candidate_action, candidate_icon, visual_fallback=False)
                    if resolved:
                        return resolved

    # Sketcher actions sometimes omit QAction command metadata, even though the
    # QToolButton tooltip contains it. Use the widget tooltip to locate exact
    # command-named theme / installed resources before visual fallback.
    widget_command = _tooltip_command_id(_safe(widget.toolTip, ''))
    if widget_command and not _freecad_command_id(action):
        roots = [x for x in (_active_icon_root(), (_theme_folder() / 'icons') if _theme_folder() else None) if x]
        for root in roots:
            for stem in (widget_command, widget_command.replace('_', '-')):
                for ext in ('.svg', '.png', '.xpm'):
                    candidate = Path(root) / (stem + ext)
                    if candidate.is_file():
                        return str(candidate.resolve()) + ' (tooltip command-name candidate; source unverified)'
    # Use the displayed widget icon and its tooltip command for Sketcher
    # split buttons before consulting the menu/default QAction.
    sketcher_match = _sketcher_resource_icon_candidate(widget, action, icon)
    if sketcher_match:
        return sketcher_match
    # Prefer a confirmed installed Mod icon filename, especially for ETC's
    # ETC_-prefixed resources and addons using command-named SVGs.
    mod_verified = _mod_command_icon_candidate(action, icon, widget_command)
    if mod_verified and 'visual match;' in mod_verified:
        return mod_verified
    # Resolve command mappings before expensive visual comparisons.
    command_match = _icon_command_candidate(action)
    if command_match:
        return command_match
    resource_match = _resource_command_candidate(action)
    if resource_match:
        return resource_match
    universal_match = _universal_resource_candidate(action, icon, widget_command)
    if universal_match:
        return universal_match
    mapped_match = _mapped_resource_candidate(action, icon)
    if mapped_match:
        return _format_icon_file_result(mapped_match)
    mod_match = _mod_command_icon_candidate(action, icon, widget_command)
    if mod_match:
        return mod_match
    match = _visual_icon_match(icon, progress=progress)
    if match:
        return match
    return 'Unknown (no metadata or matching accessible file/resource)'


def _describe(widget, pos, progress=None):
    if widget is None:
        return 'No Qt widget under the mouse pointer.', '', ''
    app = QtWidgets.QApplication.instance()
    action = _find_action(widget, pos)
    button, default_action, menu_actions = _toolbutton_context(widget, pos)
    if button is not None and menu_actions:
        shown = _safe(button.icon, None)
        shown_fp = _image_fingerprint(shown, 32) if shown is not None and not shown.isNull() else None
        selected = next((entry for entry, depth in menu_actions
                         if shown_fp is not None and
                         _image_fingerprint(_safe(entry.icon, None), 32) == shown_fp), None)
        action = selected or default_action or action
    elif button is not None and default_action is not None:
        action = default_action
    view = _find_view(widget)
    command_id = _freecad_command_id(action)
    if not command_id:
        command_id = _tooltip_command_id(_safe(widget.toolTip, ''))
    lines = ['=== UI ELEMENT ===',
             'Qt class: ' + _safe(lambda: widget.metaObject().className(), 'Unknown'),
             'Python class: ' + type(widget).__name__,
             'Object name: ' + _safe(widget.objectName, ''),
             'Window title: ' + _safe(widget.windowTitle, ''),
             'Text: ' + _safe(widget.text, '')]
    icon_result = _format_icon_file_result(_icon_file(widget, action, view, pos, progress=progress))
    lines += ['Icon file: ' + icon_result]
    icon_source = ('Sketcher command/resource candidate' if 'Sketcher command-name' in icon_result else ('Installed FreeCAD Mod icon (candidate)' if 'installed Mod' in icon_result or 'command/resource-name candidate' in icon_result else ('External theme candidate (command-name match)' if 'command-name match' in icon_result else ('Visual match (unverified source)' if 'visual match' in icon_result else 'Qt metadata / unknown'))))
    if 'command/resource name and visual match' in icon_result:
        icon_source = 'FreeCAD Qt resource / installed icon (visual match; path unverified)'
    if 'FreeCAD source mapping' in icon_result or 'FreeCAD source resource name' in icon_result:
        icon_source = 'FreeCAD core command resource (source-derived candidate)'
    lines += ['Icon source: ' + icon_source]
    if isinstance(widget, QtWidgets.QToolButton):
        lines += ['Icon size: ' + _text(_safe(widget.iconSize))]
    lines += ['Tooltip: ' + _safe(widget.toolTip, ''),
              'Visible / Enabled: %s / %s' % (_safe(widget.isVisible), _safe(widget.isEnabled)),
              'Under mouse: ' + _text(_safe(widget.underMouse)),
              'Geometry: ' + _text(_safe(lambda: widget.geometry())),
              'Logical DPI / Device pixel ratio: %s / %s' % (_safe(widget.logicalDpiX), _safe(widget.devicePixelRatioF, 1.0)),
              'Font: ' + _safe(lambda: widget.font().toString(), ''),
              'Style class: ' + _safe(lambda: widget.style().metaObject().className(), ''),
              'Palette Base: ' + _safe(lambda: widget.palette().color(QtGui.QPalette.Base).name(), ''),
              'Palette Window: ' + _safe(lambda: widget.palette().color(QtGui.QPalette.Window).name(), ''),
              'Palette Highlight: ' + _safe(lambda: widget.palette().color(QtGui.QPalette.Highlight).name(), '')]
    if isinstance(widget, QtWidgets.QAbstractButton):
        lines += ['Checked / Checkable: %s / %s' % (_safe(widget.isChecked), _safe(widget.isCheckable))]
    if command_id:
        lines += ['FreeCAD command: ' + command_id]
    lines.extend(_dropdown_action_lines(widget, pos))
    if action:
        lines += ['=== ACTION ===', 'Object name: ' + _safe(action.objectName, ''),
                  'Text: ' + _safe(action.text, ''), 'Tooltip: ' + _safe(action.toolTip, ''),
                  'Shortcut: ' + _safe(lambda: action.shortcut().toString(), ''),
                  'Enabled / checked: %s / %s' % (_safe(action.isEnabled), _safe(action.isChecked)),
                  'Icon cacheKey: ' + _text(_safe(lambda: action.icon().cacheKey()))]
    if view:
        lines += ['=== ITEM MODEL ===', 'Model: ' + _safe(lambda: view.model().metaObject().className(), ''),
                  _model_details(view, pos)]
    chain = []
    obj = widget
    for _ in range(24):
        if obj is None:
            break
        chain.append('%s#%s' % (_safe(lambda o=obj: o.metaObject().className(), '?'), _safe(obj.objectName, '')))
        obj = _safe(obj.parentWidget, None)
    lines += ['=== PARENT HIERARCHY (inner to outer) ==='] + chain
    properties = _safe(lambda: widget.dynamicPropertyNames(), [])
    if properties:
        lines += ['=== DYNAMIC PROPERTIES ===']
        for p in properties:
            name = _text(bytes(p).decode('utf-8', errors='replace'))
            lines.append('%s = %s' % (name, _text(_safe(lambda n=name: widget.property(n), ''))[:250]))
    name = _safe(widget.objectName, '')
    cls = _safe(lambda: widget.metaObject().className(), type(widget).__name__)
    selector = (cls + '#' + name) if name else cls
    return '\n'.join(lines), _sources(widget), selector


class InspectorDialog(QtWidgets.QDialog):
    def __init__(self, controller):
        super().__init__(Gui.getMainWindow())
        self.controller = controller
        self.setWindowTitle('External Theme Creator — UI Inspector')
        self.setObjectName('ExternalThemeCreatorUIInspector')
        # Use the same native dialog chrome as CFG Instructions (not Qt.Tool),
        # while keeping the inspector above FreeCAD by default.
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.WindowCloseButtonHint)
        self.setMinimumSize(760, 490)
        # The initial resize can be invalidated by Qt's later layout pass.
        # Final width is explicitly applied after the window becomes visible.
        self.resize(830, 680)
        root = QtWidgets.QVBoxLayout(self)
        self.description = QtWidgets.QLabel()
        self.description.setWordWrap(True)
        root.addWidget(self.description)
        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(QtWidgets.QLabel('Capture shortcut:'))
        self.shortcut_editor = ShortcutRecorder(controller.shortcut)
        self.shortcut_editor.shortcutRecorded.connect(controller.set_shortcut)
        self.shortcut_editor.recordingFocusChanged.connect(controller.set_recording)
        controls.addWidget(self.shortcut_editor)
        self.delayed_capture = QtWidgets.QPushButton('Capture in 3 s')
        self.delayed_capture.setToolTip('Click, then move the pointer over your target before the countdown ends.')
        self.delayed_capture.clicked.connect(controller.capture_delayed)
        controls.addWidget(self.delayed_capture)
        self.online_checkbox = QtWidgets.QCheckBox('Allow online search')
        self.online_checkbox.setToolTip('When enabled, query public source indexes for unresolved FreeCAD icon names. No GitHub account required.')
        self.online_checkbox.setChecked(controller.allow_online)
        self.online_checkbox.toggled.connect(controller.set_allow_online)
        controls.addWidget(self.online_checkbox)
        controls.addStretch()
        root.addLayout(controls)
        self.tabs = QtWidgets.QTabWidget()
        tabbar = self.tabs.tabBar()
        tabbar.setExpanding(False)
        tabbar.setUsesScrollButtons(True)
        tabbar.setElideMode(QtCore.Qt.ElideNone)
        self.tabs.setDocumentMode(False)
        self.tabs.setStyleSheet('QTabWidget::pane { border: 0px; } QTabBar::tab { min-width: 110px; padding: 7px 18px; color: #202020; background: #eeeeee; } QTabBar::tab:selected { background: #d5d5d5; font-weight: bold; }')
        # Avoid forcing tab widths: let Qt compute full natural text widths.
        self.widget_report = ReportPanel()
        self.action_report = ReportPanel()
        self.source_report = ReportPanel()
        self.tabs.addTab(self.widget_report, 'Widget')
        self.tabs.addTab(self.action_report, 'Action')
        self.tabs.addTab(self.source_report, 'QSS/CFG')
        root.addWidget(self.tabs)
        # Hidden for short inspections; a 500 ms single-shot reveals progress
        # only if icon discovery is still running.
        self.inspection_progress = QtWidgets.QProgressBar()
        self.inspection_progress.setRange(0, 100)
        self.inspection_progress.setValue(0)
        self.inspection_progress.setTextVisible(True)
        self.inspection_progress.hide()
        root.addWidget(self.inspection_progress)
        buttons = QtWidgets.QHBoxLayout()
        self.copy = QtWidgets.QPushButton('Copy details')
        self.copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.widget_report.raw_text + '\n\n' + self.action_report.raw_text + '\n\n' + self.source_report.raw_text))
        buttons.addWidget(self.copy)
        self.copy_selector = QtWidgets.QPushButton('Copy QSS selector')
        self.copy_selector.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(controller.selector))
        buttons.addWidget(self.copy_selector)
        buttons.addStretch()
        close = QtWidgets.QPushButton('Close')
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        root.addLayout(buttons)
        self.update_instruction()
        self.widget_report.set_report('Ready. Move the pointer over a widget and press ' + controller.shortcut + '.')

    def update_instruction(self):
        self.description.setText('Hover over a FreeCAD control and press %s to capture, or use the delayed capture button.' % self.controller.shortcut)

    def closeEvent(self, event):
        self.controller.stop()
        self.deleteLater()
        super().closeEvent(event)


class InspectorController(QtCore.QObject):
    def __init__(self):
        super().__init__(QtWidgets.QApplication.instance())
        # The dialog reads the shortcut while building its recorder and labels.
        # Initialize controller state first, before constructing the dialog.
        self.shortcut = _saved_shortcut()
        self.selector = ''
        self.allow_online = bool(App.ParamGet(_SETTINGS_PATH).GetBool('AllowOnlineSearch', False))
        self._network = QtNetwork.QNetworkAccessManager(self)
        self._online_request = None
        self._online_generation = 0
        self._cache_path = Path.home() / '.themecreator_icon_lookup_cache.json'
        try:
            self._online_cache = json.loads(self._cache_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self._online_cache = {}
        self._online_delay = QtCore.QTimer(self)
        self._online_delay.setSingleShot(True)
        self._online_delay.timeout.connect(self._show_online_progress)
        self.dialog = InspectorDialog(self)
        self.delayed_timer = QtCore.QTimer(self)
        self.delayed_timer.setSingleShot(True)
        self.delayed_timer.timeout.connect(self.capture)
        self._countdown_remaining = 0
        self.countdown_timer = QtCore.QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._countdown_tick)
        self.active = False
        self._recording = False
        self._inspecting = False
        self.progress_delay = QtCore.QTimer(self)
        self.progress_delay.setSingleShot(True)
        self.progress_delay.timeout.connect(self._reveal_progress)
        # Qt registers these with its shortcut map, before normal KeyPress events.
        # FreeCAD can intercept key presses before an application event filter sees them.
        shortcut_class = getattr(QtGui, 'QShortcut', None) or QtWidgets.QShortcut
        self.capture_shortcut = shortcut_class(QtGui.QKeySequence(self.shortcut), Gui.getMainWindow())
        self.capture_shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        self.capture_shortcut.activated.connect(self.capture)
        self._last_event_key = None

    def set_recording(self, recording):
        self._recording = bool(recording)
        self.capture_shortcut.setEnabled(self.active and not self._recording)

    def start(self):
        if not self.active:
            QtWidgets.QApplication.instance().installEventFilter(self)
            self.active = True
        self.capture_shortcut.setEnabled(not self._recording)
        self.dialog.show()
        self.dialog.raise_()
        # QKeySequenceEdit used to receive initial focus and intercept the first
        # keystroke as another shortcut-edit. Move focus to a non-editing control.
        self.dialog.delayed_capture.setFocus(QtCore.Qt.OtherFocusReason)
        self.set_recording(False)
        QtCore.QTimer.singleShot(0, self._apply_initial_size)

    def _apply_initial_size(self):
        try:
            dlg = self.dialog
            screen = dlg.screen() or QtWidgets.QApplication.primaryScreen()
            available = screen.availableGeometry() if screen else None
            target_width = min(830, max(760, available.width() - 60)) if available else 830
            dlg.resize(target_width, dlg.height())
        except RuntimeError:
            pass

    def _reveal_progress(self):
        if self._inspecting:
            self.dialog.inspection_progress.show()

    def _update_progress(self, value):
        self.dialog.inspection_progress.setValue(min(99, max(0, int(value))))
        # Allow the delayed visibility timer and repaint to run while matching
        # thousands of Qt icons on the GUI thread; guard against reentry.
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)

    def set_allow_online(self, value):
        self.allow_online = bool(value)
        App.ParamGet(_SETTINGS_PATH).SetBool('AllowOnlineSearch', self.allow_online)
        if not self.allow_online:
            self._cancel_online()

    def _cancel_online(self):
        self._online_generation += 1
        self._online_delay.stop()
        if self._online_request is not None:
            self._online_request.abort()
            self._online_request = None
        self.dialog.inspection_progress.hide()

    def _show_online_progress(self):
        if self._online_request is not None:
            self.dialog.inspection_progress.setRange(0, 0)
            self.dialog.inspection_progress.show()

    def _online_note(self, line):
        text = self.dialog.widget_report.raw_text
        if 'Online icon lookup:' in text:
            text = '\n'.join(x for x in text.split('\n') if not x.startswith('Online icon lookup:'))
        self.dialog.widget_report.set_report(text + '\nOnline icon lookup: ' + line)

    def _request_json(self, url, callback, generation):
        req = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        req.setRawHeader(b'User-Agent', b'ExternalThemeCreator-IconInspector/0.9.41')
        req.setRawHeader(b'Accept', b'application/json')
        self._online_request = self._network.get(req)
        reply = self._online_request
        def finished():
            if generation != self._online_generation:
                reply.deleteLater()
                return
            self._online_request = None
            try:
                err = reply.error()
                raw = bytes(reply.readAll()).decode('utf-8', 'replace')
                if err != QtNetwork.QNetworkReply.NoError:
                    raise RuntimeError(reply.errorString() + ' (HTTP ' + str(reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)) + ')')
                callback(json.loads(raw))
            except Exception as exc:
                self._finish_online('Unavailable: ' + str(exc)[:110])
            finally:
                reply.deleteLater()
        reply.finished.connect(finished)

    def _finish_online(self, text):
        self._online_delay.stop()
        self.dialog.inspection_progress.hide()
        self.dialog.inspection_progress.setRange(0, 100)
        self._online_note(text)

    def _start_online(self, command):
        if not self.allow_online or not command:
            return
        self._cancel_online()
        generation = self._online_generation
        if command in self._online_cache:
            self._finish_online(self._online_cache[command])
            return
        self._online_note('Searching public FreeCAD source index…')
        self._online_delay.start(500)
        from urllib.parse import quote
        url = 'https://grep.app/api/search?q=' + quote(command) + '&filter[repo][0]=FreeCAD/FreeCAD'
        def got_index(result):
            if generation != self._online_generation:
                return
            hits = result.get('hits', {}).get('hits', [])
            hits = [hit for hit in hits if hit.get('repo') == 'FreeCAD/FreeCAD' and hit.get('path', '').endswith(('.cpp', '.h', '.py'))]
            if not hits:
                self._finish_online('No matching FreeCAD source found in public index')
                return
            # Query source text, not repository clones or source-file downloads.
            # GitHub publishes individual public file content anonymously.
            hit = next((h for h in hits if '/Gui/' in h.get('path','') or 'Command' in h.get('path','')), hits[0])
            path = hit['path']
            url = 'https://raw.githubusercontent.com/FreeCAD/FreeCAD/main/' + quote(path, safe='/')
            request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
            request.setRawHeader(b'User-Agent', b'ExternalThemeCreator-IconInspector/0.9.41')
            self._online_request = self._network.get(request)
            reply = self._online_request
            def got_source():
                if generation != self._online_generation:
                    reply.deleteLater(); return
                self._online_request = None
                try:
                    if reply.error() != QtNetwork.QNetworkReply.NoError:
                        raise RuntimeError(reply.errorString())
                    source = bytes(reply.readAll()).decode('utf-8','replace')
                    positions = [m.start() for m in re.finditer(re.escape(command), source)]
                    found = ''
                    # Search nearby resource declarations, preferring the same command block.
                    for at in positions:
                        region = source[max(0, at-400):at+3500]
                        found_match = re.search(r'\b(?:sPixmap|Pixmap|pixmap)\s*=\s*"([^"]+)"', region)
                        if found_match:
                            found = found_match.group(1)
                            break
                    if found:
                        result = found + ' (source mapping: ' + path + '; installed-build match unverified)'
                        self._online_cache[command] = result
                        try:
                            self._cache_path.write_text(json.dumps(self._online_cache, indent=2), encoding='utf-8')
                        except OSError:
                            pass
                        self._finish_online(result)
                    else:
                        self._finish_online('Command found in ' + path + ', but no icon declaration verified')
                except Exception as exc:
                    self._finish_online('Source lookup failed: ' + str(exc)[:100])
                finally:
                    reply.deleteLater()
            reply.finished.connect(got_source)
        self._request_json(url, got_index, generation)

    def stop(self):
        self._cancel_online()
        self.progress_delay.stop()
        self._inspecting = False
        self.delayed_timer.stop()
        self.countdown_timer.stop()
        self.capture_shortcut.setEnabled(False)
        self.capture_shortcut.deleteLater()
        if self.active:
            QtWidgets.QApplication.instance().removeEventFilter(self)
            self.active = False
        global _CONTROLLER
        if _CONTROLLER is self:
            _CONTROLLER = None

    def eventFilter(self, obj, event):
        # Some FreeCAD command/viewport widgets swallow QShortcut activation, in
        # particular when the binding is a single printable key. Catch the
        # actual key press before the receiving widget processes it.
        if (self.active and not self._recording and
                event.type() == QtCore.QEvent.KeyPress and
                not event.isAutoRepeat()):
            focus = QtWidgets.QApplication.focusWidget()
            # Capture also when the modeless inspector has keyboard focus,
            # provided the key-sequence editor itself is not being edited.
            # Do not capture typing in text or shortcut-edit controls.
            if isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QTextEdit,
                                  QtWidgets.QPlainTextEdit, QtWidgets.QKeySequenceEdit,
                                  QtWidgets.QAbstractSpinBox)):
                return False
            sequence = _key_combo(event)
            if sequence and QtGui.QKeySequence(sequence) == QtGui.QKeySequence(self.shortcut):
                self.capture()
                return True
        return False

    def set_shortcut(self, shortcut):
        if not shortcut or QtGui.QKeySequence(shortcut).isEmpty():
            return
        self.shortcut = shortcut
        self.capture_shortcut.setKey(QtGui.QKeySequence(shortcut))
        try:
            App.ParamGet(_SETTINGS_PATH).SetString('CaptureShortcut', shortcut)
        except Exception:
            pass
        self.dialog.update_instruction()

    def capture_delayed(self):
        # A direct button click would only capture the button itself.
        self._countdown_remaining = 3
        self.dialog.delayed_capture.setText('Capturing in 3…')
        self.delayed_timer.start(3000)
        self.countdown_timer.start()

    def _countdown_tick(self):
        self._countdown_remaining -= 1
        if self._countdown_remaining > 0:
            self.dialog.delayed_capture.setText('Capturing in %s…' % self._countdown_remaining)
        else:
            self.countdown_timer.stop()
            self.dialog.delayed_capture.setText('Capture in 3 s')

    def capture(self):
        self.delayed_timer.stop()
        self.countdown_timer.stop()
        self.dialog.delayed_capture.setText('Capture in 3 s')
        self.inspect(QtGui.QCursor.pos(), record=True)

    def inspect(self, pos, record):
        widget = QtWidgets.QApplication.widgetAt(pos)
        if widget is not None and (widget is self.dialog or self.dialog.isAncestorOf(widget)):
            if record:
                self.dialog.widget_report.set_report('Pointer is over the inspector. Hover over FreeCAD and press ' + self.shortcut + '.')
            return
        if self._inspecting:
            return
        self._inspecting = True
        bar = self.dialog.inspection_progress
        bar.hide()
        bar.setValue(0)
        self.progress_delay.start(500)
        try:
            self._update_progress(10)
            detail, sources, selector = _describe(widget, pos, progress=self._update_progress)
            self._update_progress(95)
            self.selector = selector
            widget_report, action_report = _split_reports(detail)
            self.dialog.widget_report.set_report(widget_report)
            self.dialog.action_report.set_report(action_report)
            self.dialog.source_report.set_report(sources)
            command_match = re.search(r'^FreeCAD command: (.+)$', detail, re.MULTILINE)
            icon_line = re.search(r'^Icon file: (.+)$', detail, re.MULTILINE)
            unknown = icon_line and (icon_line.group(1).startswith('Unknown') or 'unverified' in icon_line.group(1) or 'not confirmed' in icon_line.group(1))
            if self.allow_online and command_match and unknown:
                QtCore.QTimer.singleShot(0, lambda cmd=command_match.group(1): self._start_online(cmd))
        finally:
            self.progress_delay.stop()
            self._inspecting = False
            bar.setValue(100)
            bar.hide()


def show_ui_inspector():
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = InspectorController()
    _CONTROLLER.start()


def stop_ui_inspector():
    global _CONTROLLER
    if _CONTROLLER:
        _CONTROLLER.dialog.close()
        _CONTROLLER = None
