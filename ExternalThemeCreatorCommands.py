from __future__ import annotations
import os, re, json, shutil, tempfile, zipfile, io, hashlib, base64, subprocess, sys, platform, shlex, time
from datetime import datetime, timezone
from urllib import parse as urllib_parse
from pathlib import Path
import xml.etree.ElementTree as ET
import FreeCAD as App
import FreeCADGui as Gui
try:
    from PySide import QtCore, QtGui
    try: from PySide import QtWidgets
    except Exception: QtWidgets = QtGui
except Exception:
    from PySide6 import QtCore, QtGui, QtWidgets

import ExternalThemeCreatorDependencies as _tc_deps
PARAM='User parameter:BaseApp/Preferences/ExternalThemeCreator'
QSS_KEY='DevelopmentQSSPath'; FOLDER_KEY='ThemeFolder'; THEME_KEY='ThemeFile'; CFG_FILENAME_KEY='CreatorCFGFilename'
CONFIG_NAME='theme-configuration.json'; SKIPPED_NAME='theme-configuration-skipped.json'

# Export format compatibility: kept aligned with bundled launcher engine 1.52.15.
EXTERNAL_THEME_CREATOR_VERSION='0.9.83'
UI_LAUNCHER_COMPAT_VERSION='1.52.15'
RUNTIME_DIR_NAME='.ExternalThemeCreator_runtime'
CC_LICENSES_DIR_NAME='CC_Licenses'
LICENSE_FILE_NAME='License.lic'
THEME_LICENSE_RELPATH='license/License.lic'
CUSTOM_LICENSE_OPTION='Custom License'
CUSTOM_LICENSE_BRIEF_RELPATH='license/License-brief.lic'
THEME_PACKAGE_TYPE='freecad_ui_theme'
THEME_SCHEMA_VERSION='1.0'
THEME_PAYLOAD_ENCRYPTION='launcher_v1'
THEME_PACKAGE_EXTENSION='.fctheme'
THEME_PACKAGE_OPTION_COMPLETE='Complete Theme'
THEME_PACKAGE_OPTION_ARTWORK_ONLY='Artwork Only'
THEME_PACKAGE_MODE_COMPLETE='complete_theme'
THEME_PACKAGE_MODE_ARTWORK_ONLY='artwork_only'
EXPORTABLE_THEME_EXTENSIONS={'.svg','.png','.qss','.json','.ico','.icns','.lic','.py'}
SUPPORTED_ICON_EXTENSIONS={'.svg','.png','.xpm','.ico','.icns'}
DEFAULT_LICENSE_NOTICE_BRIEF='Unless otherwise stated, the original icons, splash screens, images, and other artwork included in this *.fctheme package are subject to the terms of the included license'
DEFAULT_LICENSE_NOTICE='''License Notice

This package may contain materials under different licenses.

Unless otherwise stated, the original icons, splash screens, images, and other artwork included in this *.fctheme package are subject to the terms of the included license.

Stylesheets, FreeCAD configuration files, scripts, and other code-like files are not covered by the included license unless explicitly stated in the relevant file, folder, or accompanying notice.

Any third-party materials included in this package remain subject to their own respective license terms.'''
LICENSE_PRESET_DETAILS={
    'LGPL': {'filename':'LGPL-2.1-or-later.lic','brief':'You may use, copy, modify, and redistribute the licensed work under GNU LGPL version 2.1 or any later version. Preserve copyright and license notices, and comply with applicable source-code and relinking requirements when distributing covered software.'},
    'CC BY-ND 4.0': {'filename':'CC BY-ND 4.0.lic','brief':'Credit must be given to the creator. No derivatives or adaptations of the licensed work are permitted.'},
    'CC BY-SA 4.0': {'filename':'CC BY-SA 4.0.lic','brief':'Credit must be given to the creator. Adaptations must be shared under the same license terms.'},
    'CC_BY_4.0': {'filename':'CC_BY_4.0.lic','brief':'Credit must be given to the creator.'},
    'CC_BY-NC_4.0': {'filename':'CC_BY-NC_4.0.lic','brief':'Credit must be given to the creator. Only noncommercial use of the licensed work is permitted.'},
    'CC_BY-NC-ND_4.0': {'filename':'CC_BY-NC-ND_4.0.lic','brief':'Credit must be given to the creator. Only noncommercial use of the licensed work is permitted. No derivatives or adaptations of the licensed work are permitted.'},
    'CC_BY-NC-SA_4.0': {'filename':'CC_BY-NC-SA_4.0.lic','brief':'Credit must be given to the creator. Only noncommercial use of the licensed work is permitted. Adaptations must be shared under the same license terms.'},
}
_capture_path=None
_cfg_dialog=None
_live_icon_restore_state=None
_live_icon_restore_timer=None
_live_icon_quit_hook_connected=False
_live_icon_session=None

def mw(): return Gui.getMainWindow()
def params(): return App.ParamGet(PARAM)
def info(s): QtWidgets.QMessageBox.information(mw(),'External Theme Creator',s)
def error(s): QtWidgets.QMessageBox.critical(mw(),'External Theme Creator',s)

def _read_text(path):
    for enc in ('utf-8-sig','utf-8','utf-16'):
        try: return Path(path).read_text(encoding=enc)
        except UnicodeError: pass
    return Path(path).read_text()

def _rewrite_urls(text, base):
    pat=re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)",re.I)
    def repl(m):
        raw=m.group(2).strip()
        if not raw or raw.lower().startswith(('file:','qrc:',':','http://','https://','data:')): return m.group(0)
        p=(Path(base)/raw).resolve()
        return 'url("{}")'.format(str(p).replace('\\','/')) if p.exists() else m.group(0)
    return pat.sub(repl,text)

def _apply_qss(path):
    p=Path(path)
    if not p.is_file(): raise RuntimeError('QSS file not found: '+str(p))
    win=mw(); sizes=[]
    try:
        for tb in win.findChildren(QtWidgets.QToolBar): sizes.append((tb,tb.iconSize()))
    except Exception: pass
    app=QtWidgets.QApplication.instance()
    if app is None: raise RuntimeError('QApplication is not available.')
    # Clear any legacy main-window-local stylesheet so the application-level
    # stylesheet is the single source of truth for normal and popup widgets.
    win.setStyleSheet('')
    app.setStyleSheet(''); app.setStyleSheet(_rewrite_urls(_read_text(p),p.parent))
    for tb,size in sizes:
        try: tb.setIconSize(size)
        except Exception: pass
    Gui.updateGui(); params().SetString(QSS_KEY,str(p.resolve()))

def _find(folder, suffix):
    # Development theme source files are intentionally top-level only. Backup/copy
    # files may live in subfolders without becoming launch candidates.
    root=Path(folder)
    if not root.is_dir(): return None
    hits=sorted((p for p in root.iterdir() if p.is_file() and p.suffix.lower()==suffix), key=lambda p:p.name.lower())
    return hits[0] if hits else None

def _top_level_files(folder, suffix):
    root=Path(folder)
    if not root.is_dir(): return []
    return sorted((p for p in root.iterdir() if p.is_file() and p.suffix.lower()==suffix), key=lambda p:p.name.lower())

def _valid_cfg_filename(value):
    name=str(value or '').strip()
    return bool(name and Path(name).name==name and Path(name).suffix.lower()=='.cfg')

def _theme_scripts_enabled():
    raw=str(os.environ.get("EXTERNAL_THEME_CREATOR_UI_SCRIPTS_ENABLED","") or "").strip().lower()
    if raw in {"1","true","yes","on"}: return True
    if raw in {"0","false","no","off"}: return False
    return bool(_load_runtime_settings().get("use_external_ui_scripts",True))

def _reload_theme_scripts(reason):
    if not _theme_scripts_enabled(): return 0
    try:
        import ThemeScriptManager as TSM
        return int(TSM.reload_all(reason) or 0)
    except Exception as exc:
        App.Console.PrintWarning("External Theme Creator: theme script reload failed: "+str(exc)+"\n")
        return 0

def reload_qss():
    enabled=str(os.environ.get('EXTERNAL_THEME_CREATOR_EXTERNAL_QSS_ENABLED','') or '').strip().lower()
    if enabled in {'0','false','no','off'}:
        return error('This themed FreeCAD session was started without the external Theme Folder stylesheet.')
    p=str(os.environ.get('EXTERNAL_THEME_CREATOR_QSS_PATH','') or '').strip() or params().GetString(QSS_KEY,'').strip()
    if not p:
        folder=str(os.environ.get('EXTERNAL_THEME_CREATOR_THEME_FOLDER','') or '').strip() or params().GetString(FOLDER_KEY,'').strip(); q=_find(folder,'.qss') if folder else None; p=str(q or '')
    if not p: return error('No development QSS is active. Use Develop theme first.')
    try:
        _apply_qss(p)
        _reload_theme_scripts('qss')
        mw().statusBar().showMessage('QSS reloaded: '+p,5000)
    except Exception as e: error(str(e))

def reload_icons():
    """Reload the icon set handed off by External Theme Creator at startup.

    It also scans installed FreeCAD Mod addons for icon changes, with the Theme
    Folder taking precedence over addon resources.

    This intentionally does not browse for or infer a Theme Folder.  It only works
    in a FreeCAD process that was actually started with a theme runtime, matching
    the development semantics of QSS Reload.  The launch-time icon root is taken
    from FREECAD_EXTERNAL_ICON_THEME and the bundled launcher QSS handoff is used as a
    second guard so a normal FreeCAD session is not modified accidentally.
    """
    launcher_params=App.ParamGet('User parameter:BaseApp/Preferences/ExternalThemeCreator')
    handed_qss=launcher_params.GetString('CreatorQSSPath','').strip()
    raw_root=str(os.environ.get('FREECAD_EXTERNAL_ICON_THEME','') or '').strip()
    enabled=str(os.environ.get('FREECAD_EXTERNAL_ICON_THEME_ENABLED','') or '').strip().lower()

    if not handed_qss or not raw_root or enabled not in ('1','true','yes','on'):
        return error(
            'No active launch-time theme icon runtime was detected.\n\n'
            'Icons reload is available only when this FreeCAD session was started '
            'with a theme applied by External Theme Creator.'
        )

    root=Path(raw_root)
    if not root.is_dir():
        return error('The active theme icon folder no longer exists:\n'+str(root))

    try:
        # SVG/PNG content may have changed without the filename changing.  Clear
        # Qt's pixmap cache before creating fresh QIcons from the same paths.
        try: QtGui.QPixmapCache.clear()
        except Exception: pass
        ok,actual_root,count=_refresh_external_icons_live(root, force=True)
        if not ok:
            return error('No reloadable icons were found in the active theme icon folder:\n'+str(root))
        try: mw().statusBar().showMessage('Icons reloaded: '+str(actual_root),5000)
        except Exception: pass
        script_count=_reload_theme_scripts('icons')
        App.Console.PrintMessage(
            'External Theme Creator: reloaded active theme and FreeCAD Mod icons from:\n  '+str(actual_root)+
            '\nVisible QAction assignments on first pass: '+str(count)+
            '\nTheme-script artwork refresh hooks called: '+str(script_count)+'\n'
        )
    except Exception as e:
        error('Icons reload failed: '+str(e))

def _user_cfg():
    """Return the user CFG file actually used by the current FreeCAD process.

    A themed Creator session is normally started with an explicit --user-cfg,
    which may live outside App.getUserConfigDir().  Prefer FreeCAD's reported
    config path, then the process command line, and only then fall back to the
    conventional user.cfg location.
    """
    for key in ('UserParameter','UserConfigPath'):
        try:
            raw=str(App.ConfigGet(key) or '').strip()
        except Exception:
            raw=''
        if not raw:
            continue
        p=Path(raw).expanduser()
        if p.suffix.lower()=='.cfg':
            return p
        candidate=p/'user.cfg'
        if candidate.exists():
            return candidate
    try:
        argv=list(sys.argv)
        for i,arg in enumerate(argv):
            if arg=='--user-cfg' and i+1<len(argv):
                return Path(argv[i+1]).expanduser()
            if isinstance(arg,str) and arg.startswith('--user-cfg='):
                return Path(arg.split('=',1)[1]).expanduser()
    except Exception:
        pass
    return Path(App.getUserConfigDir())/'user.cfg'

def _flush_user_parameters():
    """Ask FreeCAD to persist current parameter/UI state before CFG snapshots."""
    try:
        fn=getattr(App,'saveParameter',None)
        if callable(fn):
            fn()
    except Exception:
        pass
    try:
        QtWidgets.QApplication.processEvents()
    except Exception:
        pass

def _parse_cfg(path):
    raw=Path(path).read_text(encoding='utf-8-sig',errors='replace')
    raw=re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]','',raw)
    root=ET.fromstring(raw); return root

def _param_map(path):
    root=_parse_cfg(path); out={}
    def walk(node, groups):
        for c in node:
            if c.tag=='FCParamGroup':
                n=c.attrib.get('Name','').strip(); walk(c,groups+([n] if n else [])); continue
            n=c.attrib.get('Name','').strip()
            if n: out[('/'.join(groups),n)]={'path':'/'.join(groups),'name':n,'type':c.tag,'value':(c.text or '') if c.tag=='FCText' else c.attrib.get('Value','')}
    walk(root,[]); return out

def _toolbar_groups(path):
    root=_parse_cfg(path); out={}
    def walk(node,groups):
        for c in node:
            if c.tag!='FCParamGroup': continue
            n=c.attrib.get('Name','').strip(); ng=groups+([n] if n else []); pp='/'.join(groups).lower(); full='/'.join(ng)
            if n.lower().startswith('custom_') and pp.endswith('/toolbar'):
                out[full]=[{'type':i.tag,'name':i.attrib.get('Name',''),'value':(i.text or '') if i.tag=='FCText' else i.attrib.get('Value','')} for i in c if i.tag!='FCParamGroup' and i.attrib.get('Name')]
            walk(c,ng)
    walk(root,[]); return out

CATS=('appearance','startup','layout','toolbars','menus','panels','navigation_view','other_ui')
TRANS={'geometry','windowstaterestored','maximized','fileopensavepath','lastmodule','lasttabindex','recentfiles','stylesheet','overlayactivestylesheet'}
def _cat(p):
    path=p['path'].lower(); name=p['name'].lower(); value=p.get('value','')
    if name in TRANS or 'stylesheet' in name: return None
    if path.rstrip('/').endswith('/preferences/mod/start') and name=='showonstartup': return 'startup'
    if path.rstrip('/').endswith('/preferences/mainwindow') and name=='mainwindowstate': return 'layout'
    if 'dockwindows/overlay' in path and name in {'width','height'}: return None
    if any(x in path for x in ('/preferences/treeview','/preferences/propertyview','/preferences/comboview')) and name.startswith('columnsize'): return None
    if len(value)>512: return None
    if '/toolbar' in path or 'toolbars' in path or 'persistenttoolbars' in path: return 'toolbars'
    if any(x in path for x in ('dockwindows','treeview','propertyview','comboview')): return 'panels'
    if path.endswith('/preferences/mainwindow'):
        if name in {'qtstyle','theme','tiledbackground'}: return 'appearance'
        if name in {'inputhintenabled','quickmeasureenabled','wsposition'}: return 'other_ui'
        return None
    if path.endswith('/preferences/general'):
        if name=='toolbariconsize': return 'toolbars'
        if name in {'showsplasher','showtaskwatcher','enablecursorblinking'}: return 'other_ui'
        return None
    if '/preferences/view' in path:
        if name.startswith('dockoverlay'): return 'panels'
        if any(x in name for x in ('color','font','textsize','iconsize','markersize','background','linewidth','pointsize','transparency','highlight','selection','axis','crosshair')): return 'appearance'
        if any(x in name for x in ('navigation','navicube','orbit','zoom','rotation','perspective','orthographic','pickradius','preselection')): return 'navigation_view'
    if '/menu' in path or 'menus' in path: return 'menus'
    if any(x in path for x in ('/mainwindow/','/preferences/ui','/preferences/gui')): return 'other_ui'
    return None

def _skip(p):
    path=p['path'].lower(); name=p['name'].lower(); val=p.get('value','')
    if 'stylesheet' in name: return 'External Theme Assets','Stylesheet content is supplied separately as the theme QSS.'
    if 'dockwindows/overlay' in path and name in {'width','height'}: return 'Transient UI State','Overlay width/height is display-dependent pixel geometry.'
    if name in TRANS or name in {'wsposition'}: return 'Transient UI State','Window/session geometry or state is not portable.'
    if len(val)>512: return 'Unclassified','Large or serialized value requires manual review.'
    if any(x in name for x in ('path','directory','filename','recent')): return 'Machine/User-specific','Setting appears user/machine-specific.'
    if '/mod/' in path or any(x in path for x in ('/preferences/units','/preferences/document','/preferences/import','/preferences/export')): return 'Non-UI Preferences','Setting is not a portable UI preference.'
    return 'Unclassified','Changed setting is not recognized by the current UI classifier.'

def generate_cfg(old,new,filename=CONFIG_NAME):
    a,b=_param_map(old),_param_map(new); ta,tb=_toolbar_groups(old),_toolbar_groups(new); cats={x:[] for x in CATS}; skipped={}
    structural=set()
    for path in sorted(set(ta)|set(tb),key=str.lower):
        if ta.get(path)==tb.get(path): continue
        structural.add(path); cats['toolbars'].append({'action':'remove_toolbar','path':path} if path not in tb else {'action':'set_toolbar','path':path,'items':tb[path]})
    for key in sorted(set(a)|set(b),key=lambda x:(x[0].lower(),x[1].lower())):
        if key[0] in structural: continue
        before,after=a.get(key),b.get(key)
        if before and after and before['type']==after['type'] and before['value']==after['value']: continue
        rep=after or before; cat=_cat(rep)
        if not cat:
            sc,reason=_skip(rep); item={'reason':reason,'action':'remove' if after is None else 'set','path':rep['path'],'name':rep['name']}
            if after: item.update(type=after['type'],value=after['value'] if len(after['value'])<=512 else '<value omitted>')
            skipped.setdefault(sc,[]).append(item); continue
        cats[cat].append({'action':'remove','path':before['path'],'name':before['name']} if after is None else {'action':'set','path':after['path'],'name':after['name'],'type':after['type'],'value':after['value']})
    ui={k:v for k,v in cats.items() if v}; n=sum(map(len,ui.values())); s=sum(map(len,skipped.values()))
    return {'schema':'ui-launcher-theme-configuration','version':3,'description':'UI-related FreeCAD configuration changes. Theme QSS is supplied separately.','output':{'filename':filename},'ui':ui,'generator_summary':{'included_ui_instructions':n,'skipped_differences':s,'review_file':SKIPPED_NAME}}, {'schema':'ui-launcher-theme-configuration-skipped','version':1,'categories':skipped,'generator_summary':{'skipped_differences':s,'accepted_ui_instructions':n}}

class PathRow(QtWidgets.QWidget):
    def __init__(self,label,folder=False,filter='All files (*)',drop_exts=None):
        super().__init__(); self.folder=folder; self.filter=filter
        self.drop_exts={str(x).lower() for x in (drop_exts or [])}
        self.setAcceptDrops(True)
        l=QtWidgets.QHBoxLayout(self); l.setContentsMargins(0,0,0,0); l.addWidget(QtWidgets.QLabel(label)); self.edit=QtWidgets.QLineEdit(); l.addWidget(self.edit,1); b=QtWidgets.QPushButton('Browse'); b.clicked.connect(self.browse); l.addWidget(b)
        if self.drop_exts:
            self.setToolTip('Drop a {} file here or use Browse.'.format('/'.join(sorted(self.drop_exts))))
            self.edit.setToolTip(self.toolTip())
    def browse(self):
        p=QtWidgets.QFileDialog.getExistingDirectory(self,'Browse',self.edit.text()) if self.folder else QtWidgets.QFileDialog.getOpenFileName(self,'Browse',self.edit.text(),self.filter)[0]
        if p:self.edit.setText(p)
    def _drop_path(self,event):
        md=event.mimeData()
        if not md or not md.hasUrls(): return None
        for url in md.urls():
            if not url.isLocalFile(): continue
            path=Path(url.toLocalFile())
            if self.folder:
                if path.is_dir(): return path
            else:
                if path.is_file() and (not self.drop_exts or path.suffix.lower() in self.drop_exts): return path
        return None
    def dragEnterEvent(self,event):
        if self._drop_path(event) is not None: event.acceptProposedAction()
        else: event.ignore()
    def dragMoveEvent(self,event):
        if self._drop_path(event) is not None: event.acceptProposedAction()
        else: event.ignore()
    def dropEvent(self,event):
        path=self._drop_path(event)
        if path is None: event.ignore(); return
        self.edit.setText(str(path.resolve()))
        event.acceptProposedAction()

def _runtime_config_dir():
    from ExternalThemeCreatorMigration import application_dir
    return application_dir()

def _runtime_settings_path(): return _runtime_config_dir()/'ExternalThemeCreator_settings.json'

def _default_packaged_theme_runtime_location():
    """Base directory used for temporary extracted packaged-theme runtimes."""
    return Path(tempfile.gettempdir()).resolve()

def _current_freecad_executable():
    candidates=[]
    exe=Path(sys.executable)
    if 'freecad' in exe.name.lower(): candidates.append(exe)
    try:
        home=Path(App.getHomePath())
        if platform.system().lower()=='windows': candidates += [home/'bin'/'FreeCAD.exe',home/'FreeCAD.exe']
        elif platform.system().lower()=='darwin': candidates += [home/'bin'/'FreeCAD',home/'MacOS'/'FreeCAD']
        else: candidates += [home/'bin'/'FreeCAD',home/'FreeCAD']
    except Exception: pass
    for c in candidates:
        if c.exists() and c.is_file(): return c.resolve()
    raise LauncherError('Could not determine the executable of the currently running FreeCAD installation.')

def _runtime_python(require_crypto=False):
    saved=params().GetString('RuntimePython','').strip();cands=[]
    if saved:cands.append(Path(saved))
    try:
        fc=_current_freecad_executable();d=fc.parent
        if platform.system().lower()=='windows': cands += [d/'python.exe',d/'pythonw.exe',d.parent/'bin'/'python.exe']
        else: cands += [d/'python3',d/'python']
    except Exception: pass
    for name in (['python','python3'] if platform.system().lower()=='windows' else ['python3','python']):
        found=shutil.which(name)
        if found:cands.append(Path(found))
    seen=set();code='import tkinter'
    for c in cands:
        try:
            key=os.path.normcase(str(c.resolve()))
            if key in seen or not c.exists():continue
            seen.add(key)
            flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
            r=subprocess.run([str(c),'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,creationflags=flags)
            if r.returncode==0:
                if require_crypto:
                    dep=_tc_deps.prepare_interpreter(c,mw())
                    if dep is None:raise LauncherError('cryptography installation was declined.')
                    os.environ['PYTHONPATH']=dep+os.pathsep+os.environ.get('PYTHONPATH','')
                params().SetString('RuntimePython',str(c.resolve()));return c.resolve()
        except LauncherError: raise
        except Exception: pass
    need=' with tkinter' 
    raise LauncherError('External Theme Creator could not find a Python interpreter'+need+'.\n\nThe embedded runtime uses the proven bundled launcher engine 1.52.15 launch engine. Select/install a Python interpreter that provides these modules, then try again.')

def _load_runtime_settings():
    sp=_runtime_settings_path()
    if sp.exists():
        try:
            data=json.loads(sp.read_text(encoding='utf-8'))
            if isinstance(data,dict): return data
        except Exception: pass
    return {}

def _save_runtime_settings(data):
    cfg=_runtime_config_dir();cfg.mkdir(parents=True,exist_ok=True)
    sp=_runtime_settings_path();sp.write_text(json.dumps(data,indent=2),encoding='utf-8');return sp

def _write_runtime_settings(mode,source):
    current=_load_runtime_settings()
    # Preserve user-selected advanced Launcher settings. Only supply defaults for
    # fields that have never been configured in External Theme Creator.
    if not str(current.get('freecad_executable','') or '').strip():
        current['freecad_executable']=str(_current_freecad_executable())
    current['use_freecad_user_home']=True
    current['close_after_freecad_launch']=True
    current.setdefault('use_external_theme_stylesheet_assets',True)
    current.setdefault('use_external_configuration',True)
    current.setdefault('use_external_ui_scripts',True)
    current['launch_mode']=mode
    if mode=='user':
        # Packaged themes always launch with every available packaged asset enabled.
        # Do not let stale advanced settings from older External Theme Creator versions
        # disable icons or inject user-specific command-line arguments.
        current['enable_external_icon_theme']=True
        current['prefer_external_icons']=True
        current['extra_cli_args']=''
        current['theme_file']=str(Path(source).expanduser().resolve())
    else:
        current.setdefault('enable_external_icon_theme',True)
        current.setdefault('prefer_external_icons',bool(current.get('enable_external_icon_theme',True)))
        current.setdefault('extra_cli_args','')
        current['theme_folder']=str(Path(source).expanduser().resolve())
    shared=_save_runtime_settings(current)
    # bundled launcher engine 1.52.15 in Python/non-frozen mode reads settings beside its
    # entry script. External Theme Creator itself may be installed under Program Files,
    # which must remain read-only. Write the identical settings beside the
    # writable mirror of the unmodified Launcher instead.
    local_settings=_ui_launcher_local_settings_path()
    local_settings.parent.mkdir(parents=True,exist_ok=True)
    local_settings.write_text(json.dumps(current,indent=2),encoding='utf-8')
    return shared

def _runtime_script():
    p=_module_dir()/'ExternalThemeCreatorRuntime.py'
    if not p.is_file():raise LauncherError('External Theme Creator runtime engine is missing:\n'+str(p))
    return p

def _ui_launcher_mirror_dir():
    # The workbench can live under a read-only installation such as Program Files.
    # Keep an exact runnable mirror of the original Launcher in the shared, writable
    # legacy launcher application-data tree. The Launcher's own _app_config_base_dir()
    # still resolves to this same root, so packaged-theme/runtime state is shared.
    return _runtime_config_dir()/'ExternalThemeCreatorLauncher'

def _sync_ui_launcher_mirror():
    src_root=_module_dir()
    src=src_root/'ExternalThemeCreatorLauncher.py'
    if not src.is_file():
        raise LauncherError('Bundled bundled launcher engine 1.52.15 runtime is missing:\n'+str(src))
    dst_root=_ui_launcher_mirror_dir()
    dst_root.mkdir(parents=True,exist_ok=True)
    dst=dst_root/'ExternalThemeCreatorLauncher.py'
    try:
        src_bytes=src.read_bytes()
        if (not dst.is_file()) or dst.read_bytes()!=src_bytes:
            dst.write_bytes(src_bytes)
    except Exception as exc:
        raise LauncherError('Could not prepare the writable external theme runtime mirror:\n'+str(exc)) from exc
    for dirname in ('Default_Shortcut_Icons','CC_Licenses'):
        s=src_root/dirname
        d=dst_root/dirname
        if s.is_dir():
            shutil.copytree(s,d,dirs_exist_ok=True)
    for filename in ('LICENSE','ExternalThemeCreatorMigration.py'):
        s=src_root/filename
        if s.is_file(): shutil.copy2(s,dst_root/filename)
    return dst

def _ui_launcher_script():
    return _sync_ui_launcher_mirror()

def _ui_launcher_local_settings_path():
    # The unmodified non-frozen Launcher expects this file beside ExternalThemeCreatorLauncher.py.
    # Use its writable mirror, never the Program Files workbench directory.
    return _ui_launcher_mirror_dir()/'ExternalThemeCreator_settings.json'

def _launch_runtime(mode,source):
    _write_runtime_settings(mode,source);py=_runtime_python(require_crypto=(mode=='user'));arg='--launch-as-user' if mode=='user' else '--launch-as-creator'
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
    return subprocess.Popen([str(py),str(_runtime_script()),arg],cwd=str(_module_dir()),creationflags=flags)


def _runtime_call(args, require_crypto=False, timeout=120):
    py=_runtime_python(require_crypto=require_crypto);flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
    r=subprocess.run([str(py),str(_runtime_script()),*map(str,args)],cwd=str(_module_dir()),text=True,capture_output=True,timeout=timeout,creationflags=flags)
    if r.returncode!=0: raise LauncherError((r.stderr or r.stdout or 'external theme runtime operation failed.').strip())
    return (r.stdout or '').strip()


def _without_reason_fields(value):
    if isinstance(value,dict):
        return {k:_without_reason_fields(v) for k,v in value.items() if k!='reason'}
    if isinstance(value,list):
        return [_without_reason_fields(v) for v in value]
    return value

def _generate_cfg_exact(old_cfg,new_cfg,filename,output_dir):
    output_dir=Path(output_dir).expanduser().resolve()
    out=_runtime_call(['--generate-cfg',str(Path(old_cfg).expanduser().resolve()),str(Path(new_cfg).expanduser().resolve()),filename,str(output_dir)])
    data=json.loads(out)
    configuration=data['configuration']
    skipped=_without_reason_fields(data['skipped'])
    # the bundled launcher writes the review file before returning it. Rewrite that file
    # without classifier prose so every instruction has the same action/path/name/
    # type/value structure used by theme-configuration.json.
    skipped_path=output_dir/SKIPPED_NAME
    if skipped_path.is_file():
        skipped_path.write_text(json.dumps(skipped,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return configuration,skipped


def _validate_creator_exact(folder):
    out=_runtime_call(['--validate-creator',str(Path(folder).expanduser().resolve())]);return json.loads(out)

def _ensure_xml_group(root, parts):
    node=root
    for part in parts:
        found=next((c for c in node if c.tag=='FCParamGroup' and c.attrib.get('Name')==part),None)
        if found is None: found=ET.SubElement(node,'FCParamGroup',{'Name':part})
        node=found
    return node

def _remove_xml_param(group,name):
    for c in list(group):
        if c.attrib.get('Name')==name: group.remove(c)

def _set_xml_param(group,name,tag,value):
    _remove_xml_param(group,name)
    if tag=='FCText':
        n=ET.SubElement(group,'FCText',{'Name':name});n.text=str(value or '')
    else: ET.SubElement(group,tag,{'Name':name,'Value':str(value or '')})

def _apply_theme_config_to_xml(cfg_path, config_path):
    data=json.loads(Path(config_path).read_text(encoding='utf-8'))
    tree=ET.parse(cfg_path);root=tree.getroot()
    for items in (data.get('ui',{}) or {}).values():
        for item in items or []:
            action=str(item.get('action','set')).lower(); path=str(item.get('path','')).strip('/')
            parts=[x for x in path.split('/') if x]
            if action=='tabify_docks':
                continue
            if action in {'set_toolbar','remove_toolbar'}:
                if not parts: continue
                parent=_ensure_xml_group(root,parts[:-1]); name=parts[-1]
                old=next((c for c in parent if c.tag=='FCParamGroup' and c.attrib.get('Name')==name),None)
                idx=list(parent).index(old) if old is not None else None
                if old is not None: parent.remove(old)
                if action=='set_toolbar':
                    tb=ET.Element('FCParamGroup',{'Name':name})
                    for e in item.get('items',[]) or []:
                        _set_xml_param(tb,str(e.get('name','')),str(e.get('type','FCText')),e.get('value',''))
                    parent.insert(idx,tb) if idx is not None else parent.append(tb)
                continue
            name=str(item.get('name',''))
            if not name: continue
            group=_ensure_xml_group(root,parts)
            if action=='remove': _remove_xml_param(group,name)
            elif action=='set': _set_xml_param(group,name,str(item.get('type','FCText')),item.get('value',''))
    tree.write(cfg_path,encoding='utf-8',xml_declaration=True)

def _write_creator_startup_qss_macro(preview, qss):
    qss=Path(qss).resolve()
    qss_text=_rewrite_urls(_read_text(qss),qss.parent)
    macro=Path(preview)/'apply_theme_creator_qss.FCMacro'
    lines=[
        'from PySide import QtCore',
        'try:',
        '    from PySide import QtWidgets',
        'except Exception:',
        '    from PySide import QtGui as QtWidgets',
        'import FreeCADGui as Gui',
        'QSS='+repr(qss_text),
        'def _apply():',
        '    try:',
        '        mw=Gui.getMainWindow()',
        '        if mw is None:',
        '            QtCore.QTimer.singleShot(200,_apply);return',
        '        sizes=[]',
        '        try:',
        '            for tb in mw.findChildren(QtWidgets.QToolBar):sizes.append((tb,tb.iconSize()))',
        '        except Exception:pass',
        '        app=QtWidgets.QApplication.instance()',
        "        if app is None: raise RuntimeError('QApplication is not available.')",
        "        mw.setStyleSheet('')",
        "        app.setStyleSheet('')",
        '        app.setStyleSheet(QSS)',
        '        for tb,size in sizes:',
        '            try:tb.setIconSize(size)',
        '            except Exception:pass',
        '        Gui.updateGui()',
        '    except Exception:',
        '        QtCore.QTimer.singleShot(250,_apply)',
        'QtCore.QTimer.singleShot(0,_apply)',
    ]
    macro.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return macro

def _prepare_creator_launch(source):
    """Prepare Creator launch through bundled launcher engine 1.52.15's exact build path.

    The workbench does not independently interpret the Theme Folder here.
    ExternalThemeCreatorRuntime invokes the bundled, unchanged ExternalThemeCreatorLauncher.py and calls
    ThemeLauncherApp.build_launch_command(), then returns that exact command and
    environment to the proven native restart helper.
    """
    folder=Path(source).expanduser().resolve()
    from ExternalThemeCreatorMigration import theme_runtime
    theme_runtime(folder)
    _write_runtime_settings('creator',folder)
    raw=_runtime_call(['--prepare-creator',str(folder)],timeout=120)
    try:
        data=json.loads(raw)
    except Exception as exc:
        raise LauncherError('external theme Creator preparation returned invalid data:\n'+str(exc)+'\n\n'+raw)
    cmd=data.get('cmd')
    env=data.get('env')
    runtime_root=Path(str(data.get('runtime_root') or (folder/RUNTIME_DIR_NAME)))
    if not isinstance(cmd,list) or not cmd:
        raise LauncherError('external theme Creator preparation did not return a launch command.')
    if not isinstance(env,dict):
        raise LauncherError('external theme Creator preparation did not return a launch environment.')
    # Keep the parity audit observational only. It receives the exact command,
    # cfg and environment produced by the bundled launcher and never alters them.
    try:
        cfg_path=Path(cmd[cmd.index('--user-cfg')+1]) if '--user-cfg' in cmd else None
        qss=_find(folder,'.qss')
        _audit_restart(folder,cfg_path,qss,env,cmd)
    except Exception:
        pass
    return [str(x) for x in cmd],{str(k):str(v) for k,v in env.items()},runtime_root

def _helper_python():
    try:
        fc=_current_freecad_executable(); d=fc.parent
        cands=[d/'python.exe',d/'pythonw.exe'] if os.name=='nt' else [d/'python3',d/'python']
        for c in cands:
            if c.is_file(): return c
    except Exception: pass
    if Path(sys.executable).is_file() and 'python' in Path(sys.executable).name.lower(): return Path(sys.executable)
    found=shutil.which('python' if os.name=='nt' else 'python3') or shutil.which('python')
    if found:return Path(found)
    raise LauncherError('Could not locate a Python interpreter for the restart helper.')

def _spawn_prepared_launch(cmd,env,preview,wait_pid=None,log_path=None,theme_splash=None):
    # The Workbench's Restart with theme bypasses UI_Launcher's normal Launch
    # button. Its detached restart helper must therefore start the custom
    # splash explicitly, after the existing FreeCAD process has exited.
    preview.mkdir(parents=True, exist_ok=True)
    preflight=preview/'splash-startup.log'
    spec=preview/'restart_spec.json'
    spec.write_text(json.dumps({
        'cmd':cmd,'env':env,'cwd':str(Path(cmd[0]).parent),
        'wait_pid':int(wait_pid or 0),'child_log':str(log_path) if log_path else '',
        'splash_image':str(theme_splash) if theme_splash else '',
        'runtime_root':str(preview),
        'splash_control':str(Path(__file__).resolve().parent/'ExternalThemeCreatorSplashControl.py'),
        'theme_folder':str(Path(theme_splash).parent.parent) if theme_splash else '',
    },indent=2),encoding='utf-8')
    helper=preview/'restart_helper.py'
    helper.write_text(r"""import os,sys,json,time,subprocess,traceback,runpy
from pathlib import Path
spec=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
root=Path(spec['runtime_root']);root.mkdir(parents=True,exist_ok=True)
def event(msg):
    with (root/'splash-startup.log').open('a',encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S')+' RESTART '+msg+'\n')
event('Detached helper entered; pid='+str(os.getpid()))
pid=int(spec.get('wait_pid') or 0)
if pid:
    if os.name=='nt':
        try:
            import ctypes
            h=ctypes.windll.kernel32.OpenProcess(0x00100000,False,pid)
            if h:
                ctypes.windll.kernel32.WaitForSingleObject(h,0xFFFFFFFF);ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            while True:
                try: os.kill(pid,0);time.sleep(.25)
                except OSError: break
    else:
        while True:
            try: os.kill(pid,0);time.sleep(.25)
            except OSError: break
splash_handle=None
splash_api=None
suppressed_cfg=None
image=Path(spec.get('splash_image') or '')
if spec.get('splash_image'):
    event('Splash requested: '+str(image))
    try:
        splash_api=runpy.run_path(spec['splash_control'],run_name='theme_creator_splash_api')
        cfg_args=spec['cmd'];cfg=Path(cfg_args[cfg_args.index('--user-cfg')+1])
        allowed,reason=splash_api['_splash_preference_allows_custom'](cfg)
        event('Splash preference: '+reason)
        if allowed and image.is_file():
            splash_handle=splash_api['_start_native_pixel_splash'](Path(spec['cmd'][0]),image,root)
        elif allowed:
            event('FALLBACK: requested splash file missing')
        if splash_handle:
            spec['cmd'],suppressed_cfg=splash_api['_prepare_suppressed_splash_launch'](spec['cmd'],cfg,root)
            event('FreeCAD native splash disabled in active theme CFG for startup; preference restored by startup macro')
            event('MODE: External Theme Creator native-resolution splash; native splash disabled')
        else:
            event('MODE: Native FreeCAD splash fallback')
    except Exception:
        event('FALLBACK: '+traceback.format_exc())
        if splash_handle:
            splash_api['_stop_native_pixel_splash'](splash_handle)
        splash_handle=None
else:
    event('No custom splash requested for this launch')
logfile=spec.get('child_log')
child_log=open(logfile,'a',encoding='utf-8') if logfile else subprocess.DEVNULL
kwargs={'cwd':spec.get('cwd') or None,'env':spec['env'],'stdin':subprocess.DEVNULL,
        'stdout':child_log,'stderr':subprocess.STDOUT if logfile else subprocess.DEVNULL}
if os.name=='nt': kwargs['creationflags']=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'DETACHED_PROCESS',0)
else: kwargs['start_new_session']=True
try:
    child=subprocess.Popen(spec['cmd'],**kwargs)
    event('FreeCAD launched pid='+str(child.pid))
except Exception:
    event('FreeCAD launch failed: '+traceback.format_exc())
    if splash_handle: splash_api['_stop_native_pixel_splash'](splash_handle)
    raise
if splash_handle:
    start=time.monotonic()
    def visible_window_for_process(target_pid):
        if os.name!='nt': return False
        import ctypes
        from ctypes import wintypes
        user32=ctypes.windll.user32
        found=[False]
        CALLBACK=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visit(hwnd,lparam):
            process_id=wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(process_id))
            if process_id.value==target_pid and user32.IsWindowVisible(hwnd):
                # Require a real, reasonably sized FreeCAD main window, not a hidden Qt helper.
                rect=wintypes.RECT()
                if user32.GetWindowRect(hwnd,ctypes.byref(rect)) and rect.right-rect.left>300 and rect.bottom-rect.top>200:
                    found[0]=True
                    return False
            return True
        user32.EnumWindows(CALLBACK(visit),0)
        return found[0]
    # FreeCAD's own splash helper uses a stop file. Wait for the main FreeCAD
    # window, not just child process creation, before requesting shutdown.
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        user32=ctypes.windll.user32
        ENUMPROC=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        def visible_window_for_process(target):
            hits=[]
            @ENUMPROC
            def visit(hwnd,lp):
                procid=wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd,ctypes.byref(procid))
                if procid.value==target and user32.IsWindowVisible(hwnd):
                    # Exclude the small/hidden utility windows.
                    rect=wintypes.RECT()
                    if user32.GetWindowRect(hwnd,ctypes.byref(rect)) and rect.right-rect.left>400 and rect.bottom-rect.top>250:
                        hits.append(hwnd)
                return True
            user32.EnumWindows(visit,0)
            return bool(hits)
    start=time.monotonic()
    while child.poll() is None and time.monotonic()-start<100:
        if os.name=='nt' and visible_window_for_process(child.pid):
            event('FreeCAD main window detected; closing replacement splash')
            break
        time.sleep(.2)
    splash_api['_stop_native_pixel_splash'](splash_handle)
    event('Splash stop requested')
""",encoding='utf-8')
    try:
        py=_helper_python()
        with preflight.open('a',encoding='utf-8') as out:
            out.write(datetime.now().isoformat(timespec='seconds')+' PARENT helper interpreter='+str(py)+'\n')
    except Exception as exc:
        with preflight.open('a',encoding='utf-8') as out:
            out.write(datetime.now().isoformat(timespec='seconds')+' PARENT ERROR helper Python: '+repr(exc)+'\n')
        raise
    kwargs={'cwd':str(preview),'stdin':subprocess.DEVNULL}
    log=open(log_path,'a',encoding='utf-8') if log_path else subprocess.DEVNULL
    kwargs.update(stdout=log,stderr=subprocess.STDOUT if log_path else subprocess.DEVNULL)
    if os.name=='nt':kwargs['creationflags']=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'DETACHED_PROCESS',0)
    else:kwargs['start_new_session']=True
    try:
        proc=subprocess.Popen([str(py),str(helper),str(spec)],**kwargs)
        with preflight.open('a',encoding='utf-8') as out:
            out.write(datetime.now().isoformat(timespec='seconds')+' PARENT spawned helper pid='+str(proc.pid)+'\n')
    except Exception as exc:
        with preflight.open('a',encoding='utf-8') as out:
            out.write(datetime.now().isoformat(timespec='seconds')+' PARENT ERROR helper spawn: '+repr(exc)+'\n')
        raise
    finally:
        if log_path:log.close()
    return proc

def _restart_runtime(mode,source,keep_current_session=False,parent=None):
    _write_runtime_settings(mode,source)

    # Creator mode uses the proven native restart helper from the 0.5.x line,
    # but _prepare_creator_launch now points at the exact same cfg/runtime files
    # that bundled launcher engine 1.52.15 uses.  No Tk/intermediate launcher process.
    if mode=='creator':
        cmd,env,runtime_root=_prepare_creator_launch(source)
        log_path=_runtime_config_dir()/'restart.log'; log_path.parent.mkdir(parents=True,exist_ok=True)
        with open(log_path,'a',encoding='utf-8') as f:
            f.write('\n--- External Theme Creator 0.6.5 restart '+datetime.now().isoformat()+' ---\n')
            f.write('Command: '+subprocess.list2cmdline(cmd)+'\n')
            f.write('Active cfg: '+str(cmd[cmd.index('--user-cfg')+1] if '--user-cfg' in cmd else '')+'\n')
            f.write('Runtime root: '+str(runtime_root)+'\n')
        if keep_current_session:
            _spawn_prepared_launch(cmd,env,runtime_root,None,log_path,theme_splash=(Path(source)/'splash'/'freecadsplash.png'))
            return True
        answer=QtWidgets.QMessageBox.question(parent or mw(),'Restart with theme','The current FreeCAD session will close and a new session will start with the enabled theme components applied.\n\nFreeCAD will still show its normal prompts for unsaved documents. Continue?',QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No,QtWidgets.QMessageBox.No)
        if answer!=QtWidgets.QMessageBox.Yes:return False
        proc=_spawn_prepared_launch(cmd,env,runtime_root,os.getpid(),log_path,theme_splash=(Path(source)/'splash'/'freecadsplash.png'))
        try:
            if parent is not None and isinstance(parent,QtWidgets.QDialog):parent.accept()
            QtWidgets.QApplication.processEvents()
        except Exception:pass
        try:accepted=bool(mw().close())
        except Exception:accepted=False
        if not accepted:
            try:proc.terminate()
            except Exception:pass
            info('Restart was cancelled because the current FreeCAD session remained open.')
            return False
        return True

    # Packaged-theme restart keeps the bundled bundled launcher user-mode engine.
    py=_runtime_python(require_crypto=True); arg='--launch-as-user'; launcher_script=_runtime_script(); base_cmd=[str(py),str(launcher_script),arg]
    launch_cwd=str(launcher_script.parent); log_path=_runtime_config_dir()/'external-theme-creator-runtime.log'; log_path.parent.mkdir(parents=True,exist_ok=True)
    if keep_current_session:
        log=open(log_path,'a',encoding='utf-8')
        kwargs={'cwd':launch_cwd,'stdin':subprocess.DEVNULL,'stdout':log,'stderr':subprocess.STDOUT}
        if os.name=='nt':kwargs['creationflags']=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'DETACHED_PROCESS',0)
        else:kwargs['start_new_session']=True
        subprocess.Popen(base_cmd,**kwargs);log.close();return True
    answer=QtWidgets.QMessageBox.question(parent or mw(),'Restart with theme','The current FreeCAD session will close and a new themed session will start. Continue?',QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No,QtWidgets.QMessageBox.No)
    if answer!=QtWidgets.QMessageBox.Yes:return False
    helper_dir=_runtime_config_dir()/'RestartHelper';helper_dir.mkdir(parents=True,exist_ok=True)
    _spawn_prepared_launch(base_cmd,dict(os.environ),helper_dir,wait_pid=os.getpid(),log_path=log_path)
    try:
        if parent is not None and isinstance(parent,QtWidgets.QDialog):parent.accept()
        QtWidgets.QApplication.processEvents()
    except Exception:pass
    try:accepted=bool(mw().close())
    except Exception:accepted=False
    if not accepted:
        info('Restart was cancelled because the current FreeCAD session remained open.');return False
    return True

def _param_uri(path):
    raw=str(path or '').strip().replace('\\','/').strip('/')
    if raw.lower().startswith('user parameter:'):return raw
    if raw.lower().startswith('root/'):raw=raw[5:]
    return 'User parameter:'+raw

def _set_live_param(path,name,typ,value):
    group=App.ParamGet(_param_uri(path));t=str(typ or 'FCText');v='' if value is None else str(value)
    if t=='FCBool':group.SetBool(name,v.strip().lower() in {'1','true','yes','on'})
    elif t=='FCInt':group.SetInt(name,int(v or 0))
    elif t in {'FCUInt','FCUnsigned'}:
        fn=getattr(group,'SetUnsigned',None) or getattr(group,'SetInt');fn(name,int(v or 0))
    elif t in {'FCFloat','FCDouble'}:group.SetFloat(name,float(v or 0))
    else:group.SetString(name,v)

def _remove_live_param(path,name,typ=None):
    group=App.ParamGet(_param_uri(path));t=str(typ or '')
    methods=[]
    if t=='FCBool':methods=['RemBool']
    elif t=='FCInt':methods=['RemInt']
    elif t in {'FCUInt','FCUnsigned'}:methods=['RemUnsigned','RemInt']
    elif t in {'FCFloat','FCDouble'}:methods=['RemFloat']
    else:methods=['RemString','RemASCII','RemInt','RemBool','RemUnsigned','RemFloat']
    for m in methods:
        fn=getattr(group,m,None)
        if fn:
            try:fn(name);return
            except Exception:pass

def _apply_live_configuration(config_path):
    p=Path(config_path)
    if not p.is_file():return (0,[])
    data=json.loads(p.read_text(encoding='utf-8'))
    ui=data.get('ui',{}) if isinstance(data,dict) else {}
    applied=0;restart=[]
    for category,items in ui.items():
        for item in items or []:
            action=str(item.get('action','set'))
            path=str(item.get('path',''))
            try:
                if action=='set':
                    _set_live_param(path,str(item.get('name','')),str(item.get('type','FCText')),item.get('value',''));applied+=1
                elif action=='remove':
                    _remove_live_param(path,str(item.get('name','')),str(item.get('type','')));applied+=1
                elif action=='tabify_docks':
                    applied+=1
                    restart.append('Dock tabification')
                elif action in {'set_toolbar','remove_toolbar'}:
                    parent_path,_,group_name=path.rstrip('/').rpartition('/')
                    parent=App.ParamGet(_param_uri(parent_path))
                    if hasattr(parent,'RemGroup'):
                        try:parent.RemGroup(group_name)
                        except Exception:pass
                    if action=='set_toolbar':
                        for entry in item.get('items',[]) or []:
                            _set_live_param(path,str(entry.get('name','')),str(entry.get('type','FCText')),entry.get('value',''))
                    applied+=1
                    restart.append('Toolbar structure/layout')
            except Exception:
                restart.append(f"Configuration: {path}/{item.get('name','')}")
        if category in {'layout','toolbars','panels','startup'} and items:
            label={'layout':'Window/dock layout','toolbars':'Toolbar layout/content','panels':'Panel structure','startup':'Startup preferences'}[category]
            restart.append(label)
    return applied,sorted(set(restart),key=str.lower)

def _find_external_icon_root(folder):
    """Find the icon-theme root. Accept icons in nested subfolders as well as directly in the root."""
    folder=Path(folder).resolve()
    def has_icons(path):
        try:
            return any(x.is_file() and x.suffix.lower() in SUPPORTED_ICON_EXTENSIONS for x in path.rglob('*'))
        except Exception:
            return False
    for name in ('icons','Icons','images','Images'):
        candidate=folder/name
        if candidate.is_dir() and has_icons(candidate): return candidate.resolve()
    if has_icons(folder): return folder
    return None

def _icon_index(root):
    """Index icons by filename stem, full filename and normalized relative path stem."""
    out={}
    root=Path(root)
    for p in root.rglob('*'):
        if not (p.is_file() and p.suffix.lower() in SUPPORTED_ICON_EXTENSIONS):
            continue
        rel=p.relative_to(root).as_posix()
        keys={
            p.stem.lower(), p.name.lower(), rel.lower(),
            re.sub(r'[^a-z0-9_\-]+','',p.stem.lower()),
            re.sub(r'[^a-z0-9_\-]+','',Path(rel).stem.lower()),
        }
        for key in keys:
            if key:
                out.setdefault(key,p)
                out.setdefault(key.replace("_","").replace("-",""),p)
    return out

def _freecad_mod_roots():
    """Discover installed and per-user FreeCAD addon directories.

    Do not modify files in these locations.  Some FreeCAD packages have a Mod
    directory under their resource directory; others use an installation-level
    Mod directory.  sys.path may contain addon module paths installed elsewhere.
    """
    candidates=[Path(__file__).resolve().parent.parent]  # current Mod, including ETC itself
    for getter in ('getResourceDir', 'getHomePath', 'getUserAppDataDir'):
        try:
            base=Path(getattr(App,getter)()).resolve()
        except Exception:
            continue
        candidates.extend((base/'Mod',base.parent/'Mod'))
    for item in sys.path:
        try:
            path=Path(item).resolve()
            if path.parent.name.lower()=='mod': candidates.append(path.parent)
            if path.name.lower()=='mod': candidates.append(path)
        except Exception:pass
    roots=[]; seen=set()
    for path in candidates:
        try:
            key=str(path).lower()
            if key in seen or not path.is_dir():continue
            seen.add(key);roots.append(path)
        except Exception:pass
    return roots


def _mod_icon_index():
    """Index icon files from FreeCAD's system and user Mod addons.

    Theme icons retain priority over installed addon icons.  The index is
    reconstructed on each manual Icons reload to pick up newly created SVGs.
    """
    index={}; files=0; addons=0
    for mod_dir in _freecad_mod_roots():
        try: addon_dirs=sorted((x for x in mod_dir.iterdir() if x.is_dir()),key=lambda x:x.name.lower())
        except OSError:continue
        for addon in addon_dirs:
            # Include ETC itself: its Resources/icons directory is editable like other addons.
            addons+=1
            try:
                for path in addon.rglob('*'):
                    try:
                        if not path.is_file() or path.suffix.lower() not in SUPPORTED_ICON_EXTENSIONS:continue
                        # Avoid scanning installed build/runtime caches under addons.
                        if any(part.lower() in ('__pycache__','.git','.externalthemecreator_runtime') for part in path.parts):continue
                        files+=1
                        rel=path.relative_to(addon).as_posix()
                        keys={path.stem.lower(),path.name.lower(),rel.lower(),
                              re.sub(r'[^a-z0-9_\-]+','',path.stem.lower())}
                        for key in keys:
                            if key:
                                index.setdefault(key,path)
                                index.setdefault(key.replace("_","").replace("-",""),path)
                    except (OSError,ValueError):continue
            except OSError:continue
    return index,addons,files


def _normalize_icon_key(value):
    if value is None: return ''
    v=str(value).strip().replace('\\','/')
    if not v: return ''
    base=Path(v).stem
    return re.sub(r'[^a-z0-9_\-]+','',base.lower())

def _command_pixmap_candidates(cmd_name, cmd=None):
    vals=[cmd_name]
    if cmd is not None:
        for meth,args in (
            ('getPixmap',()),('getResource',('Pixmap',)),('GetResources',()),
        ):
            fn=getattr(cmd,meth,None)
            if not fn: continue
            try:
                v=fn(*args)
                if isinstance(v,dict): v=v.get('Pixmap')
                if v: vals.append(str(v))
            except Exception: pass
    result=[]
    for v in vals:
        for x in (v,Path(str(v).replace('\\','/')).stem):
            k=_normalize_icon_key(x)
            if k and k not in result: result.append(k)
    return result

def _action_icon_candidates(action):
    vals=[]
    for getter in (lambda: action.objectName(), lambda: action.data()):
        try:
            v=getter()
            if v is not None and str(v).strip(): vals.append(str(v).strip())
        except Exception: pass
    result=[]
    for v in vals:
        k=_normalize_icon_key(v)
        if k and k not in result: result.append(k)
    return result

# FreeCAD command identifiers do not necessarily equal resource filenames.
# Keep ETC's native command-to-resource mapping centralized; all other addons
# continue to use discovered action and command resource metadata.
_ETC_COMMAND_ICON_STEMS = {
    'externalthemecreator_apply': 'etc_apply',
    'externalthemecreator_develop': 'etc_develop',
    'externalthemecreator_reloadqss': 'etc_reload_qss',
    'externalthemecreator_reloadicons': 'etc_reload_icons',
    'externalthemecreator_cfg': 'etc_cfg',
    'externalthemecreator_inspector': 'etc_inspector',
    'externalthemecreator_export': 'etc_export',
}


def _extended_icon_candidates(keys):
    extended = list(keys)
    for key in keys:
        alias = _ETC_COMMAND_ICON_STEMS.get(key.lower())
        if alias and alias not in extended:
            extended.append(alias)
    return extended


def _fresh_icon_from_file(path):
    """Create a new QIcon from current bytes, not Qt's SVG file-path cache."""
    path = Path(path)
    if path.suffix.lower() == '.svg':
        try:
            from PySide6 import QtSvg
            data = QtCore.QByteArray(path.read_bytes())
            renderer = QtSvg.QSvgRenderer(data)
            if renderer.isValid():
                icon = QtGui.QIcon()
                for size in (16, 20, 24, 32, 48, 64, 96, 128):
                    pixmap = QtGui.QPixmap(size, size)
                    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
                    painter = QtGui.QPainter(pixmap)
                    try: renderer.render(painter)
                    finally: painter.end()
                    icon.addPixmap(pixmap)
                return icon
        except Exception:
            pass
    pixmap = QtGui.QPixmap()
    try:
        if pixmap.loadFromData(path.read_bytes()):
            return QtGui.QIcon(pixmap)
    except Exception:
        pass
    return QtGui.QIcon(str(path))


def _find_icon_for_keys(index, keys):
    for key in keys:
        if key in index: return index[key]
        # Both indices also contain separator-free aliases, so lookups stay
        # efficient even with thousands of installed addon resource files.
        compact=key.replace('_','').replace('-','')
        if compact in index:return index[compact]
    return None

def _write_icon_live_log(lines):
    try:
        path=_runtime_config_dir()/'live-icons.log'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        return path
    except Exception:
        return None

class _LiveIconSession(QtCore.QObject):
    """Process-local icon override for the current FreeCAD session.

    FreeCAD 26.3 does not expose reloadExternalIconTheme() and command objects do
    not expose their original Pixmap through Python.  We therefore keep a map of
    Theme Folder icons and reapply them to live QAction objects whenever FreeCAD
    reconstructs a workbench/toolbars/menus.  Nothing is written to user.cfg.
    """
    def __init__(self, root, index, mod_index=None):
        super().__init__(QtWidgets.QApplication.instance())
        self.root=Path(root).resolve()
        self.index=index
        self.mod_index=mod_index or {}
        self._icon_cache={}
        self.last_workbench=''
        self.last_action_count=-1
        self.last_changed=0
        self.total_passes=0
        self._debounce=QtCore.QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(lambda:self.apply_icons('deferred GUI change'))
        self._poll_timer=QtCore.QTimer(self)
        self._poll_timer.setInterval(300)
        self._poll_timer.timeout.connect(self.poll)
        self._poll_timer.start()
        app=QtWidgets.QApplication.instance()
        if app is not None:
            try: app.installEventFilter(self)
            except Exception: pass
        try: app.aboutToQuit.connect(self.stop)
        except Exception: pass

    def stop(self):
        try:self._poll_timer.stop()
        except Exception:pass
        try:self._debounce.stop()
        except Exception:pass
        app=QtWidgets.QApplication.instance()
        if app is not None:
            try:app.removeEventFilter(self)
            except Exception:pass

    def eventFilter(self, obj, event):
        try:
            if event.type()==QtCore.QEvent.ChildAdded:
                child=getattr(event,'child',lambda:None)()
                if isinstance(child,(QtGui.QAction,QtWidgets.QToolBar,QtWidgets.QMenu)):
                    # Workbench activation can create actions/toolbars over several event-loop turns.
                    if not self._debounce.isActive(): self._debounce.start(100)
        except Exception:pass
        return False

    def _workbench_name(self):
        try:return str(Gui.activeWorkbench().name() or '')
        except Exception:return ''

    def poll(self):
        try:count=len(mw().findChildren(QtGui.QAction))
        except Exception:count=-1
        wb=self._workbench_name()
        if wb!=self.last_workbench or count!=self.last_action_count:
            self.last_workbench=wb
            self.last_action_count=count
            self.apply_icons('workbench/action set changed')
            # FreeCAD may finish constructing menus/toolbars after activation returns.
            QtCore.QTimer.singleShot(150,lambda:self.apply_icons('post-workbench 150 ms'))
            QtCore.QTimer.singleShot(500,lambda:self.apply_icons('post-workbench 500 ms'))

    def _get_fresh_icon(self, path):
        # Construct once per pass per asset. In particular, reread changed SVG
        # bytes on every manual Icons reload instead of using cached path QIcons.
        key=str(path)
        icon=self._icon_cache.get(key)
        if icon is None:
            icon=_fresh_icon_from_file(path)
            self._icon_cache[key]=icon
        return icon

    def apply_icons(self, reason='manual'):
        changed=0; matched=0
        try:actions=mw().findChildren(QtGui.QAction)
        except Exception:actions=[]
        # Direct QAction matching is the reliable Python-visible layer in FreeCAD 26.3.
        for action in actions:
            try:
                icon=(_find_icon_for_keys(self.index,_extended_icon_candidates(_action_icon_candidates(action))) or
                      _find_icon_for_keys(self.mod_index,_extended_icon_candidates(_action_icon_candidates(action))))
                if icon:
                    action.setIcon(self._get_fresh_icon(icon));changed+=1;matched+=1
            except Exception:pass
        # Command names themselves also match many FreeCAD icon filenames.  Where the
        # command exposes its QAction, update it too; do not depend on getPixmap().
        try:names=list(Gui.listCommands())
        except Exception:names=[]
        command_hits=0
        for name in names:
            keys = _extended_icon_candidates([_normalize_icon_key(name)])
            # For other addons, ask FreeCAD for their command Pixmap metadata
            # instead of assuming resource filenames match command IDs.
            try:
                cmd = Gui.Command.get(name)
                keys = _extended_icon_candidates(_command_pixmap_candidates(name, cmd))
            except Exception:
                pass
            icon=(_find_icon_for_keys(self.index,keys) or
                  _find_icon_for_keys(self.mod_index,keys))
            if not icon:continue
            command_hits+=1
            try:
                cmd=Gui.Command.get(name)
                getter=getattr(cmd,'getAction',None)
                if getter:
                    a=getter()
                    if a is not None:a.setIcon(self._get_fresh_icon(icon));changed+=1
            except Exception:pass
        try:
            QtCore.QCoreApplication.sendPostedEvents(None,0)
            QtWidgets.QApplication.processEvents();Gui.updateGui()
        except Exception:pass
        self.total_passes+=1;self.last_changed=changed
        self.last_workbench=self._workbench_name()
        try:self.last_action_count=len(mw().findChildren(QtGui.QAction))
        except Exception:pass
        return changed,matched,command_hits,reason


def _refresh_external_icons_live(folder, force=False):
    """Install a persistent, process-local icon override for the selected Theme Folder.

    When ``force`` is True, reload the icon set already handed off by the bundled launcher
    even if External Theme Creator's current Advanced preference has since been changed.
    """
    global _live_icon_session
    root=_find_external_icon_root(folder)
    if root is None:return (False,None,0)
    settings=_load_runtime_settings()
    if (not force) and (not bool(settings.get('enable_external_icon_theme',True))):return (False,root,0)

    # These environment variables are process-local.  They help any later Python-side
    # FreeCAD resolver that consults them, but unlike App.ParamGet they do not persist.
    os.environ['FREECAD_EXTERNAL_ICON_THEME']=str(root)
    os.environ['FREECAD_EXTERNAL_ICON_THEME_ENABLED']='1'
    os.environ['FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL']='1' if bool(settings.get('prefer_external_icons',True)) else '0'
    index=_icon_index(root)

    if _live_icon_session is not None:
        try:_live_icon_session.stop()
        except Exception:pass
        _live_icon_session=None

    mod_index,mod_addons,mod_files=_mod_icon_index()
    session=_LiveIconSession(root,index,mod_index)
    _live_icon_session=session
    changed,matched,command_hits,reason=session.apply_icons('initial apply')

    # FreeCAD 26.3 does not expose a general icon-theme reload API.  Existing
    # actions in the currently active workbench can retain their old icons until
    # that workbench is reconstructed.  Reproduce the successful manual
    # switch-away/switch-back behavior automatically so Apply now also refreshes
    # the workbench that was active when the command was invoked.
    active=''
    try:active=str(Gui.activeWorkbench().name() or '')
    except Exception:pass
    cycled=False
    if active and active!='NoneWorkbench':
        try:
            Gui.activateWorkbench('NoneWorkbench')
            try:
                QtCore.QCoreApplication.sendPostedEvents(None,0)
                QtWidgets.QApplication.processEvents();Gui.updateGui()
            except Exception:pass
            Gui.activateWorkbench(active)
            cycled=True
            try:
                QtCore.QCoreApplication.sendPostedEvents(None,0)
                QtWidgets.QApplication.processEvents();Gui.updateGui()
            except Exception:pass
            session.apply_icons('current workbench forced reconstruction')
        except Exception:
            cycled=False

    # Force several later passes because FreeCAD may continue constructing
    # menus/toolbars over subsequent event-loop turns.
    QtCore.QTimer.singleShot(100,lambda:session.apply_icons('initial 100 ms'))
    QtCore.QTimer.singleShot(300,lambda:session.apply_icons('initial 300 ms'))
    QtCore.QTimer.singleShot(800,lambda:session.apply_icons('initial 800 ms'))
    QtCore.QTimer.singleShot(1500,lambda:session.apply_icons('initial 1500 ms'))
    log=[
        f'External icon root: {root}',
        f'Indexed theme icon files: {len(set(index.values()))}',
        f'Indexed installed Mod icon files: {mod_files} across {mod_addons} addon directories',
        'Icon lookup priority: Theme Folder/icons first, then installed FreeCAD Mod addons (including ETC)',
        'Gui.reloadExternalIconTheme(): unavailable in this FreeCAD build; not required by the session override',
        f'Active workbench at Apply now: {active}',
        f'Current workbench forced reconstruction: {cycled}',
        f'Initial QAction icon assignments: {changed}',
        f'Initial QAction matches: {matched}',
        f'Command-name icon matches: {command_hits}',
        'Persistent process-local icon watcher: ACTIVE',
        'Icons reload scans installed Mod folders again to recognize changed addon icon files.',
        'Watcher behavior: reapplies icons after workbench/action reconstruction for the remainder of this FreeCAD session.',
        'Persistent user.cfg changes: NONE',
    ]
    log_path=_write_icon_live_log(log)
    if log_path:App.Console.PrintMessage('External Theme Creator live icon log: '+str(log_path)+'\n')
    return (True,root,changed)

def _live_cache_dir(theme_file):
    h=hashlib.sha256(str(Path(theme_file).resolve()).encode('utf-8')).hexdigest()[:16]
    return _runtime_config_dir()/'LiveThemeCache'/h

def _safe_extract_payload(payload,dest):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload),'r') as z:
        for infoz in z.infolist():
            rel=Path(infoz.filename)
            if rel.is_absolute() or '..' in rel.parts:raise LauncherError('Theme package contains an unsafe payload path.')
            target=(dest/rel).resolve()
            if dest.resolve() not in target.parents and target!=dest.resolve():raise LauncherError('Theme package contains an unsafe payload path.')
        z.extractall(dest)
    files=dest/'files'
    return files if files.is_dir() else dest

def _apply_live_folder(folder):
    """Apply only changes that can be made live without modifying normal user.cfg.

    Arbitrary FreeCAD preference instructions cannot be safely rebound to an isolated
    user.cfg after FreeCAD has already started.  Writing them through App.ParamGet()
    changes the real active configuration and persists on exit, so live Apply now
    intentionally leaves CFG/theme-configuration preferences for Restart with theme.
    """
    folder=Path(folder).resolve();restart=[];applied=[]
    q=_find(folder,'.qss')
    if q:_apply_qss(q);applied.append('QSS stylesheet')
    else:restart.append('QSS stylesheet (not found)')

    cfg_json=folder/CONFIG_NAME
    raw_cfg=_find(folder,'.cfg')
    if cfg_json.is_file():
        restart.append('Theme preferences/configuration (isolated startup configuration)')
    elif raw_cfg:
        restart.append('Raw FreeCAD .cfg configuration (isolated startup configuration)')

    splash=next((x for x in folder.rglob('*') if x.is_file() and x.suffix.lower()=='.png' and 'splash' in x.stem.lower()),None)
    if splash:restart.append('Splash screen')

    icon_root=_find_external_icon_root(folder)
    if icon_root:
        ok,root,count=_refresh_external_icons_live(folder)
        if ok:applied.append('External icon theme: '+str(root)+(f' ({count} visible actions updated)' if count else ''))
        elif not bool(_load_runtime_settings().get('enable_external_icon_theme',True)):
            restart.append('External icon theme (disabled in Advanced)')
        else:restart.append('External icon theme initialization')
    try:Gui.updateGui()
    except Exception:pass
    return applied,sorted(set(restart),key=str.lower)

def _apply_live_theme_file(theme_file):
    manifest,payload=_read_theme_package_full(theme_file)
    cache=_live_cache_dir(theme_file)
    if cache.exists():shutil.rmtree(cache,ignore_errors=True)
    folder=_safe_extract_payload(payload,cache)
    applied,restart=_apply_live_folder(folder)
    if bool(manifest.get('require_external_cfg')):restart.append('Required external CFG asset')
    if bool(manifest.get('require_external_qss')):restart.append('Required external QSS asset')
    return applied,sorted(set(restart),key=str.lower)

def _show_live_apply_result(applied,restart,parent=None):
    lines=['Theme applied to the current FreeCAD session.']
    if applied:lines += ['', 'Applied now:']+['• '+x for x in applied]
    if restart:lines += ['', 'Requires Restart with theme for full effect:']+['• '+x for x in restart]
    else:lines += ['', 'No startup-only items were detected.']
    _show_text_dialog('Theme applied', '\n'.join(lines), parent)



def _audit_dir():
    d=_runtime_config_dir()/'RuntimeAudit'
    d.mkdir(parents=True,exist_ok=True)
    return d

def _sha256_text(text):
    return hashlib.sha256(str(text).encode('utf-8')).hexdigest()

def _sha256_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def _audit_write_text(name,text):
    path=_audit_dir()/name;path.write_text(str(text),encoding='utf-8');return path

def _audit_copy(name,source):
    path=_audit_dir()/name;shutil.copy2(source,path);return path

def _launcher_reference_cfg(folder):
    """Generate the configuration the original bundled launcher engine 1.52.15 would use before startup.

    This deliberately does NOT perform External Theme Creator's Restart-specific QSS cleanup,
    so differences such as Theme / ThemeStyleParametersFile remain visible in the audit.
    """
    folder=Path(folder).resolve();out=_audit_dir()/'UILauncher-reference-user.cfg'
    raw=_find(folder,'.cfg');tc=folder/CONFIG_NAME
    if raw:
        shutil.copy2(raw,out);return out
    src=_user_cfg()
    if not src.is_file():
        ET.ElementTree(ET.Element('FCParameters')).write(out,encoding='utf-8',xml_declaration=True)
    else:shutil.copy2(src,out)
    if tc.is_file():_apply_theme_config_to_xml(out,tc)
    return out

def _cfg_audit_summary(a,b):
    if not Path(a).is_file() or not Path(b).is_file():return {'available':False}
    try:
        ma=_param_map(a);mb=_param_map(b)
        keys=sorted(set(ma)|set(mb))
        diff=[]
        for k in keys:
            av=ma.get(k);bv=mb.get(k)
            if av!=bv:
                diff.append({'path':k[0],'name':k[1],'restart':av,'launcher_reference':bv})
        ta=_toolbar_groups(a);tb=_toolbar_groups(b)
        tkeys=sorted(set(ta)|set(tb));td=[]
        for k in tkeys:
            if ta.get(k)!=tb.get(k):td.append({'toolbar':k,'restart':ta.get(k),'launcher_reference':tb.get(k)})
        return {'available':True,'parameter_difference_count':len(diff),'toolbar_difference_count':len(td),'parameter_differences':diff[:200],'toolbar_differences':td[:50]}
    except Exception as exc:return {'available':False,'error':str(exc)}

def _write_audit_report(folder):
    d=_audit_dir();folder=Path(folder).resolve()
    paths={
        'apply_source':d/'ApplyNow-source-effective.qss',
        'apply_actual':d/'ApplyNow-current-mainwindow.qss',
        'restart_qss':d/'Restart-effective.qss',
        'launcher_qss':d/'UILauncher-reference-effective.qss',
        'restart_cfg':d/'Restart-effective-user.cfg',
        'launcher_cfg':d/'UILauncher-reference-user.cfg',
        'restart_state':d/'Restart-state.json',
        'apply_state':d/'ApplyNow-state.json',
    }
    qss={}
    for key,path in paths.items():
        if path.suffix=='.qss' and path.is_file():qss[key]={'sha256':_sha256_file(path),'bytes':path.stat().st_size}
    cfgdiff=_cfg_audit_summary(paths['restart_cfg'],paths['launcher_cfg'])
    lines=[
        'External Theme Creator Runtime Parity Audit',
        'Generated: '+datetime.now().isoformat(),
        'Theme Folder: '+str(folder),
        '',
        'QSS fingerprints:',
    ]
    for key in ('apply_source','apply_actual','restart_qss','launcher_qss'):
        v=qss.get(key);lines.append(f"- {key}: "+(f"{v['sha256']} ({v['bytes']} bytes)" if v else 'not captured yet'))
    if qss.get('restart_qss') and qss.get('launcher_qss'):
        lines.append('Restart QSS == bundled engine reference QSS: '+str(qss['restart_qss']['sha256']==qss['launcher_qss']['sha256']))
    if qss.get('apply_source') and qss.get('launcher_qss'):
        lines.append('Apply-now source QSS == bundled engine reference QSS: '+str(qss['apply_source']['sha256']==qss['launcher_qss']['sha256']))
    if qss.get('apply_actual') and qss.get('launcher_qss'):
        lines.append('Current main-window QSS == bundled engine reference QSS: '+str(qss['apply_actual']['sha256']==qss['launcher_qss']['sha256']))
    lines += ['', 'Configuration comparison:']
    if cfgdiff.get('available'):
        lines.append('Restart CFG == bundled engine reference CFG (semantic): '+str(cfgdiff.get('parameter_difference_count',0)==0 and cfgdiff.get('toolbar_difference_count',0)==0))
        lines.append('Parameter differences: '+str(cfgdiff.get('parameter_difference_count',0)))
        lines.append('Toolbar structure differences: '+str(cfgdiff.get('toolbar_difference_count',0)))
        for item in cfgdiff.get('parameter_differences',[])[:40]:
            lines.append(f"  - {item['path']}/{item['name']}: restart={item['restart']!r} | launcher={item['launcher_reference']!r}")
        if cfgdiff.get('parameter_difference_count',0)>40:lines.append('  ... additional differences are in runtime-audit.json')
    else:lines.append('Restart/reference CFG comparison not available yet.')
    lines += ['', 'Captured files:']
    for key,path in paths.items():lines.append(f'- {key}: {path if path.exists() else "not captured yet"}')
    payload={'generated':datetime.now().isoformat(),'theme_folder':str(folder),'qss':qss,'configuration':cfgdiff,'files':{k:str(v) for k,v in paths.items()}}
    (d/'runtime-audit.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8')
    report=d/'runtime-audit-report.txt';report.write_text('\n'.join(lines)+'\n',encoding='utf-8');return report

def _audit_reference(folder):
    folder=Path(folder).resolve();q=_find(folder,'.qss')
    if q:
        text=_rewrite_urls(_read_text(q),q.parent)
        _audit_write_text('UILauncher-reference-effective.qss',text)
    _launcher_reference_cfg(folder)
    return _write_audit_report(folder)

def _audit_apply_now(folder):
    try:
        folder=Path(folder).resolve();q=_find(folder,'.qss')
        if q:_audit_write_text('ApplyNow-source-effective.qss',_rewrite_urls(_read_text(q),q.parent))
        actual=''
        try:actual=mw().styleSheet() or ''
        except Exception:pass
        _audit_write_text('ApplyNow-current-mainwindow.qss',actual)
        state={
            'captured':datetime.now().isoformat(),'theme_folder':str(folder),'active_workbench':str(Gui.activeWorkbench().name() if Gui.activeWorkbench() else ''),
            'qt_style':str(QtWidgets.QApplication.style().objectName() if QtWidgets.QApplication.style() else ''),
            'main_window_stylesheet_sha256':_sha256_text(actual),'main_window_stylesheet_bytes':len(actual.encode('utf-8')),
            'FREECAD_USER_HOME':os.environ.get('FREECAD_USER_HOME',''),'FREECAD_EXTERNAL_ICON_THEME':os.environ.get('FREECAD_EXTERNAL_ICON_THEME',''),
            'normal_user_cfg':str(_user_cfg()),'note':'Apply now intentionally does not apply theme CFG/preferences to protect the normal user.cfg.'
        }
        (_audit_dir()/'ApplyNow-state.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
        _audit_reference(folder)
    except Exception as exc:App.Console.PrintWarning('External Theme Creator runtime audit (Apply now) failed: '+str(exc)+'\n')

def _audit_restart(folder,isolated,qss,env,cmd):
    try:
        folder=Path(folder).resolve();_audit_copy('Restart-effective-user.cfg',isolated)
        if qss:
            qss_path=Path(qss)
            _audit_write_text('Restart-effective.qss',_rewrite_urls(_read_text(qss_path),qss_path.parent))
        state={'captured':datetime.now().isoformat(),'theme_folder':str(folder),'command':list(cmd),'environment':{k:env.get(k,'') for k in ('FREECAD_USER_HOME','FREECAD_EXTERNAL_ICON_THEME','FREECAD_EXTERNAL_ICON_THEME_ENABLED','FREECAD_EXTERNAL_ICON_THEME_PREFER_EXTERNAL')},'isolated_user_cfg':str(isolated)}
        (_audit_dir()/'Restart-state.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
        _audit_reference(folder)
    except Exception as exc:App.Console.PrintWarning('External Theme Creator runtime audit (Restart) failed: '+str(exc)+'\n')

def _show_runtime_parity_audit(parent,source):
    if not source:raise LauncherError('Select a Theme Folder first.')
    folder=Path(source).expanduser().resolve()
    if not folder.is_dir():raise LauncherError('Theme Folder does not exist.')
    report=_audit_reference(folder)
    text=report.read_text(encoding='utf-8')+'\nAudit folder:\n'+str(_audit_dir())+'\n\nRun Apply now and Restart with theme once each, then reopen this report for a complete comparison.'
    _show_text_dialog('Runtime parity audit',text,parent)

def _create_shortcut(mode,source,parent):
    _write_runtime_settings(mode,source)
    dlg=QtWidgets.QDialog(parent);dlg.setWindowTitle('Create shortcut');lay=QtWidgets.QFormLayout(dlg)
    name=QtWidgets.QLineEdit('FreeCAD');location=QtWidgets.QLineEdit(str(Path.home()/'Desktop'));row=QtWidgets.QWidget();rh=QtWidgets.QHBoxLayout(row);rh.setContentsMargins(0,0,0,0);rh.addWidget(location,1);browse=QtWidgets.QPushButton('Browse');rh.addWidget(browse)
    browse.clicked.connect(lambda: (lambda x: location.setText(x) if x else None)(QtWidgets.QFileDialog.getExistingDirectory(dlg,'Shortcut Location',location.text())))
    lay.addRow('Shortcut Name',name);lay.addRow('Shortcut Location',row);bb=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel);bb.accepted.connect(dlg.accept);bb.rejected.connect(dlg.reject);lay.addRow(bb)
    if dlg.exec()!=QtWidgets.QDialog.Accepted:return
    py=_runtime_python(require_crypto=(mode=='user'));arg='--create-shortcut-user' if mode=='user' else '--create-shortcut-creator';flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
    runtime_args=[str(py),str(_runtime_script()),arg,name.text().strip() or 'FreeCAD',location.text().strip()]
    r=subprocess.run(runtime_args,cwd=str(_module_dir()),text=True,capture_output=True,creationflags=flags)
    if r.returncode!=0:raise LauncherError((r.stderr or r.stdout or 'Shortcut creation failed.').strip())
    info('Shortcut created successfully:\n'+(r.stdout.strip() or location.text().strip()))

def _browse_freecad_executable(parent, edit):
    system=platform.system().lower(); current=edit.text().strip()
    if system=='darwin':
        selected=QtWidgets.QFileDialog.getExistingDirectory(parent,'Select FreeCAD.app',str(Path(current).parent if current else Path.home()))
    else:
        filt='FreeCAD executable (FreeCAD.exe);;Executables (*.exe);;All files (*)' if system=='windows' else 'All files (*)'
        selected=QtWidgets.QFileDialog.getOpenFileName(parent,'Select FreeCAD executable',current or str(Path.home()),filt)[0]
    if selected:edit.setText(selected)

def refresh_live_icons():
    """Reapply the currently active External Theme Creator session icon override."""
    if _live_icon_session is None:
        return False
    _live_icon_session.apply_icons('manual refresh')
    return True

def _copy_reload_command():
    text="import ExternalThemeCreatorCommands as TC\nTC.refresh_live_icons()"
    cb=QtWidgets.QApplication.clipboard();cb.setText(text)
    try:mw().statusBar().showMessage('External Theme Creator live icon refresh command copied.',4000)
    except Exception:pass

def _run_runtime_diagnostics(parent=None):
    py=_runtime_python(require_crypto=False);flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
    try:
        r=subprocess.run([str(py),str(_runtime_script()),'--diagnostics-creator'],cwd=str(_module_dir()),text=True,capture_output=True,timeout=60,creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise LauncherError('Theme Configuration Diagnostics timed out after 60 seconds.') from exc
    report=(r.stdout or '').strip()
    if r.returncode!=0:
        raise LauncherError((r.stderr or report or 'Theme Configuration Diagnostics failed.').strip())
    _show_text_dialog('Theme Configuration Diagnostics',report or 'Diagnostics completed without output.',parent)

class AdvancedDialog(QtWidgets.QDialog):
    def __init__(self,parent=None,mode=None,source=None):
        super().__init__(parent or mw())
        self.setWindowTitle('Settings')
        self.resize(820,610 if mode=='creator' else 300)
        self.mode=mode;self.source=source
        data=_load_runtime_settings()
        v=QtWidgets.QVBoxLayout(self)
        form=QtWidgets.QGridLayout();v.addLayout(form)
        row=0
        self.folder=None; self.cfgname=None; self.theme_runtime_location=None
        self.suppress_splash_info=None
        if mode=='creator':
            form.addWidget(QtWidgets.QLabel('Theme Folder'),row,0)
            self.folder=QtWidgets.QLineEdit(str(data.get('theme_folder','') or params().GetString(FOLDER_KEY,'')))
            form.addWidget(self.folder,row,1,1,2)
            fb=QtWidgets.QPushButton('Browse');fb.clicked.connect(self.browse_theme_folder);form.addWidget(fb,row,3);row+=1
            form.addWidget(QtWidgets.QLabel('.cfg filename'),row,0)
            default_cfg=str(data.get('creator_cfg_filename','') or params().GetString(CFG_FILENAME_KEY,'')).strip()
            if not default_cfg:
                try:
                    f=Path(self.folder.text().strip()).expanduser()
                    cfgs=_top_level_files(f,'.cfg') if f.is_dir() else []
                    if len(cfgs)==1: default_cfg=cfgs[0].name
                    elif (f/CONFIG_NAME).is_file():
                        tc=json.loads((f/CONFIG_NAME).read_text(encoding='utf-8')); default_cfg=str((tc.get('output') or {}).get('filename') or '').strip()
                except Exception:pass
            if not default_cfg:default_cfg='FreeCAD Theme.cfg'
            self.cfgname=QtWidgets.QLineEdit(default_cfg)
            self.cfgname.setToolTip('Filename only, ending in .cfg. Used when external configuration is enabled.')
            form.addWidget(self.cfgname,row,1,1,3);row+=1
        form.addWidget(QtWidgets.QLabel('FreeCAD executable'),row,0)
        self.exe=QtWidgets.QLineEdit(str(data.get('freecad_executable','') or ''))
        if not self.exe.text().strip():
            try:self.exe.setText(str(_current_freecad_executable()))
            except Exception:pass
        form.addWidget(self.exe,row,1)
        b=QtWidgets.QPushButton('Browse');b.clicked.connect(lambda:_browse_freecad_executable(self,self.exe));form.addWidget(b,row,2)
        cur=QtWidgets.QPushButton('Current FreeCAD');cur.clicked.connect(self.use_current);form.addWidget(cur,row,3);row+=1
        if mode=='user':
            form.addWidget(QtWidgets.QLabel('Theme runtime location'),row,0)
            runtime_default=str(data.get('theme_runtime_location','') or _default_packaged_theme_runtime_location())
            self.theme_runtime_location=QtWidgets.QLineEdit(runtime_default)
            self.theme_runtime_location.setToolTip('Base folder used for the temporary runtime created when FreeCAD starts from a .fctheme package.')
            form.addWidget(self.theme_runtime_location,row,1,1,2)
            rb=QtWidgets.QPushButton('Browse');rb.clicked.connect(self.browse_theme_runtime_location);form.addWidget(rb,row,3);row+=1

        self.icons=None; self.args=None
        self.external_qss=None; self.external_cfg=None; self.external_scripts=None
        if mode=='creator':
            self.icons=QtWidgets.QCheckBox('Use external theme icons')
            self.icons.setChecked(bool(data.get('enable_external_icon_theme',data.get('prefer_external_icons',True))))
            form.addWidget(self.icons,row,0,1,4);row+=1
            self.external_qss=QtWidgets.QCheckBox('Use external theme stylesheet (.qss) and assets')
            self.external_qss.setChecked(bool(data.get('use_external_theme_stylesheet_assets',True)))
            self.external_qss.setToolTip('When enabled, load the top-level theme .qss and its Theme Folder\\qss-assets resources. When disabled, use the normal system-user stylesheet.')
            form.addWidget(self.external_qss,row,0,1,4);row+=1
            self.external_cfg=QtWidgets.QCheckBox('Use external configuration (.cfg)')
            self.external_cfg.setChecked(bool(data.get('use_external_configuration',True)))
            self.external_cfg.setToolTip('When enabled, use/generate the configured Theme Folder .cfg. When disabled, ignore Theme Folder .cfg files and use the normal system-user configuration.')
            form.addWidget(self.external_cfg,row,0,1,4);row+=1
            self.external_scripts=QtWidgets.QCheckBox('Use external UI scripts')
            self.external_scripts.setChecked(bool(data.get('use_external_ui_scripts',True)))
            self.external_scripts.setToolTip('Load optional Python runtime scripts from Theme Folder\\scripts after the GUI and QSS are ready.')
            form.addWidget(self.external_scripts,row,0,1,4);row+=1
            form.addWidget(QtWidgets.QLabel('Extra FreeCAD command-line arguments'),row,0)
            self.args=QtWidgets.QLineEdit(str(data.get('extra_cli_args','') or ''));form.addWidget(self.args,row,1,1,3);row+=1

            line=QtWidgets.QFrame();line.setFrameShape(QtWidgets.QFrame.HLine);v.addWidget(line)
            actions=QtWidgets.QHBoxLayout();v.addLayout(actions)
            diag=QtWidgets.QPushButton('Theme Configuration Diagnostics');diag.clicked.connect(self.diagnostics);actions.addWidget(diag)
            copy=QtWidgets.QPushButton('Copy external-icon reload command');copy.clicked.connect(_copy_reload_command);actions.addWidget(copy)
            actions.addStretch()
            self.status=QtWidgets.QPlainTextEdit();self.status.setReadOnly(True);v.addWidget(self.status,1);self.refresh_status()
        else:
            # Packaged themes always use the isolated runtime and every available
            # packaged asset. The user-mode Settings window therefore only needs
            # the target FreeCAD executable.
            self.status=None

        bb=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel);bb.accepted.connect(self.accept);bb.rejected.connect(self.reject);v.addWidget(bb)

    def browse_theme_folder(self):
        current=self.folder.text().strip() if self.folder is not None else ''
        selected=QtWidgets.QFileDialog.getExistingDirectory(self,'Select Theme Folder',current or str(Path.home()))
        if selected:self.folder.setText(selected);self.refresh_status()
    def browse_theme_runtime_location(self):
        if self.theme_runtime_location is None:return
        current=self.theme_runtime_location.text().strip() or str(_default_packaged_theme_runtime_location())
        selected=QtWidgets.QFileDialog.getExistingDirectory(self,'Select Theme Runtime Location',current)
        if selected:self.theme_runtime_location.setText(selected)
    def use_current(self):
        try:self.exe.setText(str(_current_freecad_executable()))
        except Exception as exc:error(str(exc))
    def _collect(self):
        data=_load_runtime_settings();exe=self.exe.text().strip()
        if not exe:raise LauncherError('FreeCAD executable cannot be empty.')
        data['freecad_executable']=exe
        data['use_freecad_user_home']=True
        data['close_after_freecad_launch']=True
        # Restart with theme is intentionally a true restart: never keep the current session.
        params().SetBool('RestartWithThemeInNewSession',False)
        if self.mode:data['launch_mode']=self.mode
        if self.mode=='creator':
            data['enable_external_icon_theme']=self.icons.isChecked()
            data['prefer_external_icons']=self.icons.isChecked()
            data['extra_cli_args']=self.args.text().strip()
            folder_text=self.folder.text().strip() if self.folder is not None else ''
            if not folder_text:raise LauncherError('Theme Folder cannot be empty.')
            folder=Path(folder_text).expanduser().resolve()
            cfgname=self.cfgname.text().strip() if self.cfgname is not None else ''
            use_external_cfg=bool(self.external_cfg.isChecked())
            if use_external_cfg and not _valid_cfg_filename(cfgname):
                try:
                    tc_path=folder/CONFIG_NAME
                    if tc_path.is_file():
                        tc=json.loads(tc_path.read_text(encoding='utf-8'))
                        candidate=str((tc.get('output') or {}).get('filename') or '').strip()
                        if _valid_cfg_filename(candidate): cfgname=candidate
                    if not _valid_cfg_filename(cfgname):
                        cfgs=_top_level_files(folder,'.cfg')
                        if len(cfgs)==1: cfgname=cfgs[0].name
                except Exception:
                    pass
            if use_external_cfg and not _valid_cfg_filename(cfgname):
                raise LauncherError('.cfg filename must be a filename ending in .cfg, or theme-configuration.json must provide output.filename.')
            data['theme_folder']=str(folder);data['creator_cfg_filename']=cfgname
            data['use_external_theme_stylesheet_assets']=bool(self.external_qss.isChecked())
            data['use_external_configuration']=use_external_cfg
            data['use_external_ui_scripts']=bool(self.external_scripts.isChecked())
            params().SetString(FOLDER_KEY,str(folder));params().SetString(CFG_FILENAME_KEY,cfgname)
        elif self.mode=='user':
            # Packaged themes always launch with every asset contained in the
            # package enabled. These forced values also neutralize stale settings
            # saved by older External Theme Creator releases.
            data['enable_external_icon_theme']=True
            data['prefer_external_icons']=True
            data['extra_cli_args']=''
            runtime_text=self.theme_runtime_location.text().strip() if self.theme_runtime_location is not None else ''
            runtime_path=Path(runtime_text or _default_packaged_theme_runtime_location()).expanduser().resolve()
            runtime_path.mkdir(parents=True,exist_ok=True)
            data['theme_runtime_location']=str(runtime_path)
            if self.source:
                data['theme_file']=str(Path(self.source).expanduser().resolve())
        return data
    def accept(self):
        try:_save_runtime_settings(self._collect());super().accept()
        except Exception as exc:error(str(exc))
    def diagnostics(self):
        try:_save_runtime_settings(self._collect());_run_runtime_diagnostics(self)
        except Exception as exc:error(str(exc))
    def refresh_status(self):
        if self.status is None:return
        lines=['External Theme Creator settings','',f"Settings file: {_runtime_settings_path()}",f"Launch mode: {self.mode or '(not specified)'}"]
        if self.mode=='creator':
            folder_text=self.folder.text().strip() if self.folder is not None else ''
            lines += [
                f"Theme Folder: {folder_text or '(not selected)'}",
                f".cfg filename: {self.cfgname.text().strip() if self.cfgname is not None else '(not set)'}",
                f"Use external stylesheet/assets: {self.external_qss.isChecked()}",
                f"Use external configuration: {self.external_cfg.isChecked()}",
                f"Use external UI scripts: {self.external_scripts.isChecked()}",
                '',
                'Required Theme Folder subfolders:',
                '  icons/       - custom theme icons',
                '  license/     - License.lic',
                '  qss-assets/  - stylesheet image/SVG assets',
                '  scripts/     - optional theme runtime Python scripts',
                '  shortcut-icon/ - Custom_Icon.icns/.ico/.png',
                '  splash/      - freecadsplash.png',
            ]
        lines += [
            f"FreeCAD executable: {self.exe.text().strip() or '(not selected)'}",
            'FREECAD_USER_HOME runtime isolation: always enabled',
            f"External icons: {self.icons.isChecked()}",
            'Close External Theme Creator dialog after launch: always enabled',
            'Restart with theme: always closes the current FreeCAD session first',
            f"Extra CLI arguments: {self.args.text().strip() or '(none)'}",
        ]
        self.status.setPlainText('\n'.join(lines))

def _open_advanced(parent,mode=None,source=None):
    AdvancedDialog(parent,mode,source).exec()

class ApplyDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(mw())
        self.setWindowTitle('Apply theme')
        self.resize(760,140)
        self._accepted_path = None
        self._accepted_license = None
        self._reviewed_path = None
        v=QtWidgets.QVBoxLayout(self)
        # The spaces surrounding License Brief must be explicit and stable.
        v.setSpacing(0)
        self.path=PathRow('Theme file',False,'FreeCAD Theme (*.fctheme);;All files (*)',drop_exts={'.fctheme'})
        self.path.edit.setText(params().GetString(THEME_KEY,''))
        v.addWidget(self.path)
        v.addSpacing(10)
        h=QtWidgets.QHBoxLayout()
        h.setSpacing(10)  # exact gap between Apply theme action buttons
        v.addLayout(h)
        self.launch_buttons=[]
        for label,fn in [('License',self.show_license),('Settings',self.settings),('Create shortcut',self.shortcut),('Restart with theme',self.restart)]:
            button=QtWidgets.QPushButton(label)
            button.clicked.connect(fn)
            h.addWidget(button)
            if label in ('Create shortcut','Restart with theme'):
                self.launch_buttons.append(button)
        h.addStretch()
        # Show metadata and the license brief only after license acceptance.
        # Keep their spacing inside the section so hiding it collapses the dialog.
        self.details_section=QtWidgets.QWidget(self)
        details=QtWidgets.QVBoxLayout(self.details_section)
        details.setContentsMargins(0,0,0,0)
        details.setSpacing(0)
        details.addSpacing(10)
        self.package_versions=QtWidgets.QLabel('Theme created with: —\nTheme tested with: —')
        self.package_versions.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        details.addWidget(self.package_versions)
        details.addSpacing(30)  # exact space above the License Brief label
        details.addWidget(QtWidgets.QLabel('License Brief'))
        details.addSpacing(10)  # exact space below the License Brief label
        self.notice=QtWidgets.QPlainTextEdit()
        self.notice.setReadOnly(True)
        self.notice.setFixedHeight(90)
        details.addWidget(self.notice)
        v.addWidget(self.details_section)
        self.details_section.hide()
        self._notice_timer=QtCore.QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(250)
        self._notice_timer.timeout.connect(self._review_selection)
        self.path.edit.textChanged.connect(self._selection_changed)
        self._set_launch_enabled(False)
        if self.path.edit.text().strip():
            QtCore.QTimer.singleShot(0,self._review_selection)

    def _set_launch_enabled(self,enabled):
        for button in self.launch_buttons:
            button.setEnabled(bool(enabled))

    def _set_details_visible(self,visible):
        self.details_section.setVisible(bool(visible))
        # Restore compact dialog height before acceptance; show all content
        # after acceptance without leaving a large blank area.
        self.layout().activate()
        wanted=max(self.minimumSizeHint().height(),self.sizeHint().height())
        self.resize(self.width(),wanted)

    def _selection_changed(self,*_args):
        self._accepted_path=None
        self._accepted_license=None
        self._reviewed_path=None
        self.notice.clear()
        self.package_versions.setText('Theme created with: —\nTheme tested with: —')
        self._set_launch_enabled(False)
        self._set_details_visible(False)
        self._notice_timer.start()

    def _path(self):
        p=Path(self.path.edit.text()).expanduser()
        if not p.is_file() or p.suffix.lower()!='.fctheme':
            raise LauncherError('Select a valid .fctheme file.')
        return p.resolve()

    def _license_dialog(self,license_text):
        dialog=QtWidgets.QDialog(self)
        dialog.setWindowTitle('Theme License')
        dialog.resize(740,540)
        layout=QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel('Please review the license before using this theme.'))
        editor=QtWidgets.QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(license_text)
        layout.addWidget(editor,1)
        buttons=QtWidgets.QDialogButtonBox()
        cancel=buttons.addButton('Cancel',QtWidgets.QDialogButtonBox.RejectRole)
        accept=buttons.addButton('Accept License',QtWidgets.QDialogButtonBox.AcceptRole)
        cancel.clicked.connect(dialog.reject)
        accept.clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        return dialog.exec()==QtWidgets.QDialog.Accepted

    def _review_selection(self):
        raw=self.path.edit.text().strip()
        if not raw:
            return
        try:
            path=self._path()
        except Exception:
            return  # Incomplete paths should not trigger error popups while typing.
        if self._accepted_path==path:
            return
        if self._reviewed_path==path:
            return  # Cancel does not repeatedly reopen the dialog.
        self._reviewed_path=path
        try:
            manifest,license_text=_theme_package_license_text(path)
            created=str(manifest.get('theme_creator_version') or '').strip() or 'Not recorded (older theme)'
            tested=str(manifest.get('freecad_version_tested') or '').strip() or 'Not recorded'
            self.package_versions.setText('Theme created with: '+created+'\nTheme tested with: '+tested)
            if not license_text.strip():
                self.notice.setPlainText('This theme does not contain a readable License.lic.')
                return
            if self._license_dialog(license_text):
                self._accepted_path=path
                self._accepted_license=license_text
                self.notice.setPlainText(_package_license_brief(path,manifest))
                self._set_details_visible(True)
                # A package is encrypted and signed, so the first license read
                # already needs cryptography. Verify the private installation
                # again upon acceptance, before enabling either launch action.
                # ensure_current prompts for permission if setup is required;
                # it performs import, signing, and encryption diagnostics.
                try:
                    if not _tc_deps.ensure_current(self):
                        self.notice.setPlainText('License accepted, but cryptography setup was declined.\nUse License to retry dependency setup.')
                        self._set_launch_enabled(False)
                        return
                except Exception as setup_error:
                    self.notice.setPlainText('License accepted, but cryptography diagnostics failed:\n'+str(setup_error))
                    self._set_launch_enabled(False)
                    return
                self._set_launch_enabled(True)
            else:
                self.notice.setPlainText('License not accepted. Select License to review it again.')
        except Exception as exc:
            self.notice.setPlainText('Unable to read theme license:\n'+str(exc))

    def show_license(self):
        try:
            self._reviewed_path=None
            self._accepted_path=None
            self._accepted_license=None
            self._set_launch_enabled(False)
            self._set_details_visible(False)
            self._review_selection()
        except Exception as exc:
            error(str(exc))

    def _require_acceptance(self):
        path=self._path()
        if path!=self._accepted_path:
            self._reviewed_path=None
            self._review_selection()
        if path!=self._accepted_path:
            raise LauncherError('Accept the theme license before continuing.')
        # Recheck license content in case the selected package was replaced.
        manifest,license_text=_theme_package_license_text(path)
        if license_text!=self._accepted_license:
            self._accepted_path=None
            self._accepted_license=None
            self._reviewed_path=None
            self._set_launch_enabled(False)
            self._set_details_visible(False)
            self._review_selection()
            if path!=self._accepted_path:
                raise LauncherError('The theme license changed. Accept the new license before continuing.')
        return path

    def settings(self):
        source=self.path.edit.text().strip() or None
        _open_advanced(self,'user',source)

    def restart(self):
        try:
            path=self._require_acceptance()
            params().SetString(THEME_KEY,str(path))
            _restart_runtime('user',path,False,self)
        except Exception as exc:error(str(exc))

    def shortcut(self):
        try:
            path=self._require_acceptance()
            params().SetString(THEME_KEY,str(path))
            _create_shortcut('user',path,self)
        except Exception as exc:error(str(exc))


def _package_license_brief(path,manifest):
    # New packages include the brief as a separate asset. Older packages
    # store it only in manifest metadata.
    _,payload=_read_theme_package_full(path)
    with zipfile.ZipFile(io.BytesIO(payload),'r') as archive:
        for candidate in ('files/'+CUSTOM_LICENSE_BRIEF_RELPATH,CUSTOM_LICENSE_BRIEF_RELPATH):
            if candidate in archive.namelist():
                return archive.read(candidate).decode('utf-8',errors='replace').strip()
    return str(manifest.get('license_terms','') or 'No license brief is available.').strip()

# Development helpers intentionally operate on the working Theme Folder, not
# the generated runtime. They do not apply or change the running theme.
_SPLASH_PREVIEW_WINDOWS = []


def _preview_theme_splash(folder, parent=None, on_closed=None):
    source = Path(folder) / 'splash' / 'freecadsplash.png'
    if not source.is_file():
        QtWidgets.QMessageBox.information(parent or mw(), 'Display splash',
            'No splash graphic was found in the selected Theme Folder.\n\n'
            'Expected: splash/freecadsplash.png')
        return
    pixmap = QtGui.QPixmap(str(source))
    if pixmap.isNull():
        raise LauncherError('The splash image cannot be loaded:\n' + str(source))

    # PNG pixels should map to physical screen pixels, not logical Qt pixels.
    # A 150%-scaled monitor otherwise displays an 800px PNG 1200px wide.
    # setDevicePixelRatio adjusts the pixmap's logical size WITHOUT resampling.
    screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
    if screen is None:
        screen = QtGui.QGuiApplication.primaryScreen()
    dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
    if dpr > 0:
        pixmap.setDevicePixelRatio(dpr)

    class _SplashPreview(QtWidgets.QSplashScreen):
        """Preview the PNG through Qt's real splash-screen widget."""
        def __init__(self):
            super().__init__(pixmap, QtCore.Qt.WindowStaysOnTopHint)
            self.setWindowTitle('Splash preview')
            self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
            # High-DPI pixmaps have *physical* pixel dimensions larger than
            # their widget's logical dimensions. Never apply pixmap.mask() to
            # the QWidget: that mask is in physical pixels and clips the splash
            # at 125%/150%/200% display scaling.
            # Use alpha compositing instead of a binary shape mask.
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            logical = pixmap.deviceIndependentSize()
            self.setFixedSize(max(1, round(logical.width())),
                              max(1, round(logical.height())))
            self.clearMask()
        def mousePressEvent(self, event):
            self.close()
        def keyPressEvent(self, event):
            if event.key() == QtCore.Qt.Key_Escape:
                self.close()
            else:
                super().keyPressEvent(event)
        def closeEvent(self, event):
            try: _SPLASH_PREVIEW_WINDOWS.remove(self)
            except ValueError: pass
            if on_closed is not None:
                try: on_closed(self)
                except Exception: pass
            super().closeEvent(event)

    window = _SplashPreview()
    _SPLASH_PREVIEW_WINDOWS.append(window)
    if screen is not None:
        area = screen.availableGeometry()
        window.move(area.center().x() - window.width() // 2,
                    area.center().y() - window.height() // 2)
    window.show()
    # QSplashScreen or the platform may install a pixmap-sized shape mask
    # during show(). Ensure transparency is instead composed through alpha.
    window.clearMask()
    window.raise_()
    window.activateWindow()
    return window


_THEME_FOLDER_ROOT_GUIDE = """External Theme Creator — Theme Folder
============================

Place these files at the top level of this Theme Folder:

One .qss file
    The FreeCAD/Qt stylesheet. Images referenced by it belong in qss-assets/.
    When external stylesheet/assets are enabled, exactly one top-level .qss
    file is expected.

One .cfg file
    The independent persistent FreeCAD configuration for Develop theme.
    FreeCAD reads and saves settings directly to this file; it is NOT the normal
    FreeCAD user.cfg or the configuration of an applied .fctheme package.
    If this folder has no .cfg yet, External Theme Creator creates one by copying the
    normal FreeCAD configuration and applying theme-configuration.json when
    external configuration is enabled. Changes made in the development
    session are saved here, so this is your working development configuration.
    Keep only one top-level .cfg file.

theme-configuration.json
    FreeCAD configuration instructions used to initialize a missing development
    .cfg when external configuration is enabled. The JSON is not a second .cfg.
    You can create or update this file automatically: in External Theme Creator, open
    CFG instructions, capture configuration changes, select the captured
    instruction blocks, and click "Add selection to the CFG instructions".
    If the file does not exist, External Theme Creator creates it with the required
    JSON structure and adds the selected instructions.
    Alternatively, create the file using "Compare and generate CFG
    instructions (.json)" in the same CFG instructions dialog. Select an old
    and a new FreeCAD .cfg file to generate the configuration differences.
    This generator will not overwrite an existing theme-configuration.json;
    it displays a warning instead.

theme-configuration-skipped.json
    Optional record of skipped/transient configuration instructions, not
    applied as active configuration.

The six asset subfolders contain icons, licenses, QSS resources, scripts,
shortcut icons and splash artwork. Each has its own README.txt.

Development runtime
-------------------
During Develop theme, generated launch helpers and a separate user home live
inside .ExternalThemeCreator_runtime/ in this Theme Folder. The single top-level .cfg
remains the active development configuration; there is no second active
configuration in .ExternalThemeCreator_runtime/development_profile/.

The four external-asset switches control the assets that are loaded, not the
isolation of the development environment. Turning off external configuration
prevents applying theme-configuration.json and layout instructions, but keeps
using the existing isolated development .cfg.

During Export theme, External Theme Creator automatically skips the entire
.ExternalThemeCreator_runtime/ folder. Its generated runtime files and private user
home are not included in the exported theme package.
"""


_THEME_FOLDER_GUIDES = {
    'icons': ('Theme icons',
              'Place custom SVG, PNG, or other supported icon files here. '
              'External Theme Creator registers this folder as an external FreeCAD icon directory. '
              'Use FreeCAD icon resource names, for example preferences-sketcher.svg.'),
    'license': ('License files',
                'Place License.lic (full license) and License-brief.lic '
                '(summary shown during theme application) here. '
                'Custom License exports use these documents.'),
    'qss-assets': ('QSS stylesheet resources',
                   'Place images, SVG graphics, and other assets referenced by your '
                   'root-level .qss stylesheet here. Use relative URLs in the QSS.'),
    'scripts': ('UI scripts',
                'Place optional Python .py runtime scripts here. They are loaded '
                'only when external UI scripts are enabled.'),
    'shortcut-icon': ('Shortcut icons',
                      'Place Custom_Icon.ico (Windows), Custom_Icon.icns (macOS), '
                      'and Custom_Icon.png (fallback/other systems) here.'),
    'splash': ('Splash image',
               'Place freecadsplash.png here. The PNG is used at its native '
               'pixel dimensions; edit the source image to change its size.'),
}


class CreateThemeFolderDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw())
        self.setWindowTitle('Create Theme Folder')
        self.setMinimumWidth(540)
        layout = QtWidgets.QFormLayout(self)
        self.parent_path = QtWidgets.QLineEdit(str(Path.home()))
        browse = QtWidgets.QPushButton('Browse')
        browse.clicked.connect(self._browse)
        folder_row = QtWidgets.QWidget(self)
        row_layout = QtWidgets.QHBoxLayout(folder_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.parent_path, 1)
        row_layout.addWidget(browse)
        layout.addRow('Parent folder:', folder_row)
        self.folder_name = QtWidgets.QLineEdit('Theme Folder')
        layout.addRow('Folder name:', self.folder_name)
        self.info_label = QtWidgets.QLabel('Creates the six expected asset subfolders, '
                                           'each with a short README.txt, plus a root README.txt. No example assets are added.')
        self.info_label.setWordWrap(True)
        layout.addRow(self.info_label)
        controls = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                               QtWidgets.QDialogButtonBox.Cancel)
        controls.button(QtWidgets.QDialogButtonBox.Ok).setText('Create Folder')
        controls.accepted.connect(self._create)
        controls.rejected.connect(self.reject)
        layout.addRow(controls)
        self.created_folder = None

    def _browse(self):
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Select parent folder', self.parent_path.text().strip() or str(Path.home()))
        if selected: self.parent_path.setText(selected)

    def _create(self):
        parent = Path(self.parent_path.text().strip()).expanduser()
        name = self.folder_name.text().strip()
        if not parent.is_dir():
            QtWidgets.QMessageBox.warning(self, 'Create Theme Folder',
                                           'Select an existing parent folder.')
            return
        if not name or name in ('.', '..') or any(x in name for x in '/\\<>:"|?*'):
            QtWidgets.QMessageBox.warning(self, 'Create Theme Folder',
                                           'Enter a valid folder name.')
            return
        target = parent / name
        if target.exists():
            QtWidgets.QMessageBox.warning(self, 'Create Theme Folder',
                'This folder already exists. Select another name to avoid overwriting files.')
            return
        try:
            target.mkdir()
            (target / 'README.txt').write_text(_THEME_FOLDER_ROOT_GUIDE, encoding='utf-8')
            for subfolder, (title, instructions) in _THEME_FOLDER_GUIDES.items():
                child = target / subfolder
                child.mkdir()
                (child / 'README.txt').write_text(title + '\n' + '='*len(title) +
                                                   '\n\n' + instructions + '\n', encoding='utf-8')
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, 'Create Theme Folder',
                                           'Could not create the folder:\n' + str(exc))
            return
        self.created_folder = target.resolve()
        self.accept()


class DevelopDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(mw())
        self.setWindowTitle('Develop theme')
        self.resize(470, 190)
        self._splash_window = None
        layout = QtWidgets.QVBoxLayout(self)
        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid)
        button_specs = [
            ('Create Theme Folder', self.create_theme_folder),
            ('Restart with theme', self.restart),
            ('Create shortcut', self.shortcut),
            ('Display splash', self.display_splash),
            ('Validate', self.validate),
            ('Settings', self.advanced),
        ]
        for i, (text, callback) in enumerate(button_specs):
            button = QtWidgets.QPushButton(text, self)
            button.clicked.connect(callback)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                 QtWidgets.QSizePolicy.Preferred)
            grid.addWidget(button, i // 2, i % 2)
            if text == 'Display splash':
                self._splash_button = button
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        # Clear the initial QPushButton focus/auto-default highlight.
        for i in range(grid.count()):
            widget = grid.itemAt(i).widget()
            if isinstance(widget, QtWidgets.QPushButton):
                widget.setAutoDefault(False)
                widget.setDefault(False)
                widget.setFocusPolicy(QtCore.Qt.NoFocus)

    def _splash_closed(self, window):
        if self._splash_window is window:
            self._splash_window = None
            self._splash_button.setText('Display splash')

    def display_splash(self):
        if self._splash_window is not None:
            self._splash_window.close()
            return
        try:
            window = _preview_theme_splash(self._folder(), self,
                                           on_closed=self._splash_closed)
            if window is not None:
                self._splash_window = window
                self._splash_button.setText('Hide splash')
        except Exception as exc:
            error(str(exc))

    def closeEvent(self, event):
        if self._splash_window is not None:
            self._splash_window.close()
        super().closeEvent(event)

    def create_theme_folder(self):
        dialog = CreateThemeFolderDialog(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.created_folder:
            path = str(dialog.created_folder)
            QtWidgets.QMessageBox.information(self, 'Create Theme Folder',
                'Theme Folder created:\n' + path +
                '\n\nThe Theme Folder selection in Settings was not changed.')

    def _folder(self):
        data=_load_runtime_settings();raw=str(data.get('theme_folder','') or params().GetString(FOLDER_KEY,'')).strip()
        if not raw:raise LauncherError('Theme Folder is not selected. Open Settings and choose the Theme Folder.')
        p=Path(raw).expanduser()
        if not p.is_dir():raise LauncherError('Theme Folder does not exist or is not a folder. Open Settings to update it.')
        return p.resolve()
    def _require_launch_ready(self,p):
        result=_validate_creator_exact(p)
        if not result.get('ok'):
            raise LauncherError('\n'.join(result.get('errors') or ['Theme Folder validation failed.']))
        return result
    def validate(self):
        try:
            p=self._folder(); result=_validate_creator_exact(p)
            lines=['Theme Folder: '+str(p),'QSS: '+(result.get('qss') or 'system user / disabled'),'QSS assets folder: '+str(result.get('qss_assets') or (p/'qss-assets')),'CFG: '+(result.get('cfg') or 'system user / disabled'),'Scripts folder: '+str(result.get('scripts') or (p/'scripts')),'Splash: '+(result.get('splash') or 'not found'),'Theme icons/assets: '+('found' if result.get('icon_root') else 'not found')]
            if result.get('warnings'): lines += ['','Warnings:']+['• '+str(x) for x in result.get('warnings',[])]
            if result.get('errors'): lines += ['','Errors:']+['• '+str(x) for x in result.get('errors',[])]
            else: lines += ['','Ready to launch.']
            _show_text_dialog('Theme Folder validation','\n'.join(lines),self)
        except Exception as exc:error(str(exc))
    def advanced(self):
        _open_advanced(self,'creator',None)
    def apply(self):
        try:
            p=self._folder();qss=_top_level_files(p,'.qss')
            if len(qss)!=1:raise LauncherError(f'Theme Folder must contain exactly one top-level .qss file; found {len(qss)}. Move backup copies into a subfolder.')
            q=qss[0];params().SetString(FOLDER_KEY,str(p));params().SetString(QSS_KEY,str(q.resolve()))
            applied,restart=_apply_live_folder(p);_audit_apply_now(p);_show_live_apply_result(applied,restart,self)
        except Exception as exc:error(str(exc))
    def restart(self):
        try:
            p=self._folder();result=self._require_launch_ready(p);params().SetString(FOLDER_KEY,str(p))
            q=str(result.get('qss') or '').strip()
            if q: params().SetString(QSS_KEY,str(Path(q).resolve()))
            _restart_runtime('creator',p,False,self)
        except Exception as exc:error(str(exc))
    def shortcut(self):
        try:
            p=self._folder();result=self._require_launch_ready(p);params().SetString(FOLDER_KEY,str(p))
            q=str(result.get('qss') or '').strip()
            if q: params().SetString(QSS_KEY,str(Path(q).resolve()))
            _create_shortcut('creator',p,self)
        except Exception as exc:error(str(exc))

def _show_text_dialog(title,text,parent=None):
    d=QtWidgets.QDialog(parent or mw());d.setWindowTitle(title);d.resize(720,520);v=QtWidgets.QVBoxLayout(d);box=QtWidgets.QPlainTextEdit();box.setReadOnly(True);box.setPlainText(str(text));v.addWidget(box,1);b=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close);b.rejected.connect(d.reject);b.clicked.connect(d.accept);v.addWidget(b);d.exec()

def _theme_folder_for_cfg_tools():
    data=_load_runtime_settings()
    raw=str(data.get('theme_folder','') or params().GetString(FOLDER_KEY,'')).strip()
    if not raw:
        raise LauncherError('Theme Folder is not selected. Open Develop theme → Settings and choose it first.')
    folder=Path(raw).expanduser().resolve()
    if not folder.is_dir():
        raise LauncherError('Theme Folder does not exist:\n'+str(folder))
    return folder

def _configured_cfg_filename_for_instructions(folder=None, fallback=''):
    folder=Path(folder or _theme_folder_for_cfg_tools()).resolve()
    data=_load_runtime_settings()
    name=str(data.get('creator_cfg_filename','') or params().GetString(CFG_FILENAME_KEY,'')).strip()
    if _valid_cfg_filename(name): return name
    tc=folder/CONFIG_NAME
    if tc.is_file():
        try:
            candidate=str(((json.loads(tc.read_text(encoding='utf-8')).get('output') or {}).get('filename') or '')).strip()
            if _valid_cfg_filename(candidate): return candidate
        except Exception: pass
    fallback=str(fallback or '').strip()
    if _valid_cfg_filename(fallback): return fallback
    cfgs=_top_level_files(folder,'.cfg')
    if len(cfgs)==1:return cfgs[0].name
    return 'FreeCAD Theme.cfg'

def _set_configured_cfg_filename(name, folder=None, sync_json=True):
    name=str(name or '').strip()
    if not _valid_cfg_filename(name):
        raise LauncherError('CFG filename must be a filename ending in .cfg, without a folder path.')
    data=_load_runtime_settings();data['creator_cfg_filename']=name;_save_runtime_settings(data)
    params().SetString(CFG_FILENAME_KEY,name)
    if folder is not None and sync_json:
        folder=Path(folder).expanduser().resolve()
        target=folder/CONFIG_NAME
        if target.is_file():
            cfg=json.loads(target.read_text(encoding='utf-8'))
            if not isinstance(cfg,dict):
                raise LauncherError('theme-configuration.json is not a JSON object.')
            cfg.setdefault('output',{})['filename']=name
            _write_theme_configuration(target,cfg)
    return name

def _instructions_json_path(folder, filename):
    name=str(filename or CONFIG_NAME).strip() or CONFIG_NAME
    if Path(name).name!=name or Path(name).suffix.lower()!='.json':
        raise LauncherError('CFG instructions filename must be a filename ending in .json.')
    return Path(folder)/name

def _dock_ref_key(value):
    if isinstance(value,dict):
        for key in ('object_name','fallback_title','title','name'):
            text=str(value.get(key,'') or '').strip()
            if text:return text.lower()
        return ''
    return str(value or '').strip().lower()

def _instruction_key(item):
    action=str(item.get('action','')).lower()
    if action in {'set_toolbar','remove_toolbar'}:
        return ('toolbar',str(item.get('path','')).lower())
    if action=='tabify_docks':
        return ('tabify_docks',_dock_ref_key(item.get('primary')),_dock_ref_key(item.get('secondary')))
    return ('param',str(item.get('path','')).lower(),str(item.get('name','')).lower())

def _instruction_sort_key(item):
    k=_instruction_key(item)
    return (*k,str(item.get('action','')).lower())

def _sort_theme_configuration_data(data):
    if not isinstance(data,dict):return data
    out={}
    for key in ('schema','version','description','output'):
        if key in data:out[key]=data[key]
    ui=data.get('ui',{})
    if isinstance(ui,dict):
        ordered={}
        keys=list(ui.keys())
        rank={name:i for i,name in enumerate(CATS)}
        for cat in sorted(keys,key=lambda x:(rank.get(x,10000),str(x).lower())):
            items=ui.get(cat)
            if isinstance(items,list):
                ordered[cat]=sorted(items,key=_instruction_sort_key)
            else:
                ordered[cat]=items
        out['ui']=ordered
    for key,value in data.items():
        if key not in out and key!='ui':out[key]=value
    return out

def _write_theme_configuration(path,data):
    data=_sort_theme_configuration_data(data)
    Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return data

def _blank_theme_configuration(cfg_filename):
    return {
        'schema':'ui-launcher-theme-configuration',
        'version':3,
        'description':'UI-related FreeCAD configuration changes. Theme QSS is supplied separately.',
        'output':{'filename':cfg_filename},
        'ui':{},
    }

_SERIALIZED_UI_STATE_NAMES={
    'mainwindowstate','windowstaterestored','dockwindowstate','toolbarstate'
}

def _looks_like_base64_blob(value):
    s=''.join(str(value or '').split())
    if len(s)<80:return False
    if not re.fullmatch(r'[A-Za-z0-9+/]*={0,2}',s):return False
    # Long Qt saveState() payloads are normally Base64-like and may contain
    # many '/' characters. Those slashes must never be treated as path separators.
    return True

def _serialized_ui_state(name,value):
    lname=str(name or '').strip().lower()
    if lname in _SERIALIZED_UI_STATE_NAMES:return True
    return ('state' in lname and _looks_like_base64_blob(value))

def _portable_value_dependency(value):
    """Return (kind, explanation) for a real OS/user path dependency, else None.

    Deliberately does NOT normalize '/' to '\\'. That old behavior made Base64
    data such as Qt MainWindowState look like a UNC path.
    """
    s=str(value or '').strip()
    if not s:return None
    low=s.lower()

    # Environment/user expansion tokens are dependencies even before expansion.
    env_patterns=(
        (r'(?i)%appdata%|%localappdata%|%userprofile%|%homedrive%|%homepath%',
         'Windows environment-variable dependency'),
        (r'(?i)%programfiles(?:\(x86\))?%|%programw6432%',
         'Windows installation-path environment dependency'),
        (r'(?i)(?<![A-Za-z0-9_])\$home(?![A-Za-z0-9_])|\$\{home\}|\$\{user\}|\$\{userprofile\}',
         'Unix/macOS user-home environment dependency'),
        (r'(?:(?<=^)|(?<=[\s=:\"\']))~[\\/]',
         'User-home (~) path dependency'),
    )
    for pat,kind in env_patterns:
        if re.search(pat,s):return kind,kind+'.'

    # Windows drive paths: C:\..., C:/... at the start or after a separator.
    if re.search(r'(?i)(?:^|[\s=;,(\[\{\"\'])[a-z]:[\\/][^\s]*',s):
        return 'Windows absolute path','Value contains a Windows drive-letter absolute path.'

    # UNC/network paths must genuinely begin with two backslashes and contain
    # server/share components. Merely having repeated slashes inside Base64 is not enough.
    if re.search(r'(?i)(?:^|[\s=;,(\[\{\"\'])\\\\[^\\/\s]+[\\/][^\\/\s]+',s):
        return 'Windows UNC/network path','Value contains a UNC/network path.'

    # Explicit user-profile directories on either slash convention.
    if re.search(r'(?i)(?:^|[\\/])users[\\/][^\\/\s]+[\\/]',s):
        return 'Windows user-profile path','Value contains a Windows user-profile path.'
    if re.search(r'(?i)(?:^|[\\/])appdata[\\/](?:roaming|local|locallow)(?:[\\/]|$)',s):
        return 'Windows AppData path','Value contains a Windows AppData path.'
    if re.search(r'(?i)(?:^|[\\/])program files(?: \(x86\))?[\\/]',s):
        return 'Windows installation path','Value contains a Windows Program Files path.'

    # POSIX paths. Require a recognizable absolute root rather than any '/'.
    posix_patterns=(
        (r'(?:^|[\s=;,(\[\{\"\'])/Users/[^/\s]+(?:/|$)','macOS user-home path'),
        (r'(?:^|[\s=;,(\[\{\"\'])/home/[^/\s]+(?:/|$)','Linux user-home path'),
        (r'(?:^|[\s=;,(\[\{\"\'])/(?:tmp|var/tmp)(?:/|$)','temporary-directory path'),
        (r'(?:^|[\s=;,(\[\{\"\'])/(?:Applications|Library)(?:/|$)','macOS system path'),
        (r'(?:^|[\s=;,(\[\{\"\'])/(?:usr|opt|etc)(?:/|$)','Unix/Linux system path'),
    )
    for pat,kind in posix_patterns:
        if re.search(pat,s):return kind,'Value contains a '+kind+'.'

    return None

def _portable_value_problem(value):
    # Compatibility wrapper used by older call sites.
    return _portable_value_dependency(value) is not None

def _dock_ref_display(value):
    if isinstance(value,dict):
        for key in ('object_name','fallback_title','title','name'):
            text=str(value.get(key,'') or '').strip()
            if text:return text
        return ''
    return str(value or '').strip()

def _instruction_target_text(item):
    if not isinstance(item,dict):return ''
    action=str(item.get('action','') or '').lower()
    path=str(item.get('path','') or '').strip()
    if action in {'set_toolbar','remove_toolbar'}:
        return path
    if action=='tabify_docks':
        return '{} <-> {}'.format(_dock_ref_display(item.get('primary')),_dock_ref_display(item.get('secondary')))
    name=str(item.get('name','') or '').strip()
    return path + ((' -> '+name) if name else '')

def _validation_issue(severity,title,explanation,category=None,index=None,item=None,counterpart=None):
    issue={
        'severity':str(severity),
        'title':str(title),
        'explanation':str(explanation),
        'category':category,
        'index':index,
        'instruction':item if isinstance(item,dict) else None,
        'target':_instruction_target_text(item),
    }
    if isinstance(counterpart,dict):issue['counterpart']=counterpart
    return issue

def _line_col_for_offset(text,pos):
    pos=max(0,min(len(text),int(pos)))
    return text.count('\n',0,pos)+1, pos-(text.rfind('\n',0,pos)+1)+1

def _next_nonspace(text,pos):
    i=max(0,int(pos))
    while i<len(text) and text[i].isspace():i+=1
    return i

def _prev_nonspace(text,pos):
    i=min(len(text)-1,int(pos))
    while i>=0 and text[i].isspace():i-=1
    return i

def _json_error_progresses(candidate,old_pos):
    try:
        json.loads(candidate);return True
    except json.JSONDecodeError as exc:
        return exc.pos>old_pos
    except Exception:
        return False

def _try_repair_minor_json_syntax(raw,max_repairs=20):
    """Conservatively repair small punctuation mistakes in JSON.

    Only changes that let the JSON parser move beyond the original error are
    accepted. This intentionally handles punctuation mistakes (missing commas
    and trailing commas), not guessed keys, values, quotes, or braces.
    """
    text=str(raw);repairs=[]
    for _ in range(max_repairs):
        try:return json.loads(text),text,repairs
        except json.JSONDecodeError as exc:
            pos=exc.pos;msg=str(exc.msg or '')
            j=_next_nonspace(text,pos);i=_prev_nonspace(text,j-1)
            changed=False
            # Missing comma between adjacent JSON values / object members.
            if "Expecting ',' delimiter" in msg and j<len(text) and i>=0:
                prev=text[i];cur=text[j]
                value_end = prev in '}]"0123456789el.' # object/array/string/number/true-false/null endings
                next_start = cur in '{["-0123456789tfn'
                if value_end and next_start:
                    candidate=text[:j]+','+text[j:]
                    if _json_error_progresses(candidate,pos):
                        line,col=_line_col_for_offset(text,j)
                        repairs.append('Inserted missing comma before line {}, column {}.'.format(line,col))
                        text=candidate;changed=True
            # Trailing comma before a closing object/array.
            if not changed and ("Expecting property name enclosed in double quotes" in msg or "Expecting value" in msg) and j<len(text) and text[j] in '}]':
                k=_prev_nonspace(text,j-1)
                if k>=0 and text[k]==',':
                    candidate=text[:k]+text[k+1:]
                    if _json_error_progresses(candidate,pos) or candidate.strip():
                        try:
                            json.loads(candidate);progress=True
                        except json.JSONDecodeError as exc2:
                            progress=exc2.pos>=max(0,pos-1)
                        except Exception:progress=False
                        if progress:
                            line,col=_line_col_for_offset(text,k)
                            repairs.append('Removed trailing comma at line {}, column {}.'.format(line,col))
                            text=candidate;changed=True
            if not changed:return None,raw,repairs
        except Exception:
            return None,raw,repairs
    try:return json.loads(text),text,repairs
    except Exception:return None,raw,repairs

def _write_json_repair_backup(path,raw):
    path=Path(path)
    base=Path(str(path)+'.bak')
    candidate=base;n=1
    while candidate.exists():
        candidate=Path(str(base)+'.'+str(n));n+=1
    candidate.write_text(raw,encoding='utf-8')
    return candidate

def _validate_theme_configuration_file(path):
    path=Path(path)
    errors=[];warnings=[];portability=[];info=[];issues=[]
    def add(severity,message,title=None,explanation=None,category=None,index=None,item=None,counterpart=None):
        message=str(message)
        if severity=='error':errors.append(message)
        elif severity=='warning':warnings.append(message)
        else:portability.append(message)
        issues.append(_validation_issue(
            severity,
            title or ('Error' if severity=='error' else ('Warning' if severity=='warning' else 'Portability note')),
            explanation or message,
            category,index,item,counterpart
        ))
    if not path.is_file():
        add('error','File does not exist: '+str(path),'File not found','The configured CFG instructions file does not exist.')
        return None,errors,warnings,portability,info,issues
    try:
        raw=path.read_text(encoding='utf-8')
        data=json.loads(raw)
    except json.JSONDecodeError as exc:
        repaired,repaired_text,repairs=_try_repair_minor_json_syntax(raw)
        if repaired is None or not repairs:
            add('error','JSON syntax error: '+str(exc),'JSON syntax error','The JSON parser could not read the file. External Theme Creator could not safely repair this syntax error automatically; review the reported line/column manually.')
            return None,errors,warnings,portability,info,issues
        try:
            backup=_write_json_repair_backup(path,raw)
            path.write_text(repaired_text,encoding='utf-8')
            data=repaired
            info.append('Auto-repaired minor JSON syntax: '+' '.join(repairs))
            info.append('Original file backed up to: '+str(backup))
        except Exception as repair_exc:
            add('error','JSON syntax error: '+str(exc),'JSON syntax error','A safe punctuation repair was found, but External Theme Creator could not save it: '+str(repair_exc))
            return None,errors,warnings,portability,info,issues
    except Exception as exc:
        add('error','Could not read JSON: '+str(exc),'Could not read file','External Theme Creator could not read or parse the CFG instructions file.')
        return None,errors,warnings,portability,info,issues
    if not isinstance(data,dict):
        add('error','Top-level JSON value must be an object.','Invalid top-level JSON','theme-configuration.json must begin with a JSON object containing schema, output, and ui blocks.')
        return data,errors,warnings,portability,info,issues
    if data.get('schema')!='ui-launcher-theme-configuration':
        add('warning','Unexpected or missing schema value.','Unexpected schema','The schema should be "ui-launcher-theme-configuration" so External Theme Creator can reliably identify this file.')
    if data.get('version')!=3:
        add('warning','Expected theme-configuration version 3.','Unexpected configuration version','External Theme Creator currently expects theme-configuration version 3.')
    output=data.get('output')
    if not isinstance(output,dict):
        add('error','Missing or invalid output block.','Missing output block','The output block tells External Theme Creator which .cfg filename to create when a Theme Folder CFG is missing.')
    else:
        fn=str(output.get('filename','') or '').strip()
        if not _valid_cfg_filename(fn):
            add('error','output.filename must be a filename ending in .cfg.','Invalid CFG output filename','output.filename must contain only a filename ending in .cfg, without a folder path.')
    ui=data.get('ui')
    if not isinstance(ui,dict):
        add('error','ui must be an object containing instruction sections.','Invalid ui block','The ui value must be an object whose keys are instruction sections such as appearance, layout, toolbars, and panels.')
    else:
        allowed_types={'FCBool','FCInt','FCUInt','FCFloat','FCString','FCText'}
        allowed_actions={'set','remove','set_toolbar','remove_toolbar','tabify_docks'}
        seen={}
        total=0
        for cat,items in ui.items():
            if cat not in CATS:
                add('warning','Non-standard instruction section: '+str(cat),'Non-standard instruction section','This section is not one of External Theme Creator\'s standard UI categories. It can still be retained, but review it for portability.',cat,None,None)
            if not isinstance(items,list):
                add('error','Section {} must contain a list of instructions.'.format(cat),'Invalid instruction section','The section must contain a JSON array/list of instruction blocks.',cat,None,None)
                continue
            for idx,item in enumerate(items,1):
                total+=1
                loc='{} instruction {}'.format(cat,idx)
                if not isinstance(item,dict):
                    add('error',loc+' is not an object.','Invalid instruction block','Each instruction must be a JSON object containing an action and target.',cat,idx,None)
                    continue
                action=str(item.get('action','')).lower()
                if action not in allowed_actions:
                    add('error',loc+' has invalid action: '+repr(action),'Invalid instruction action','Supported actions are set, remove, set_toolbar, remove_toolbar, and tabify_docks.',cat,idx,item)
                    continue
                if action=='tabify_docks':
                    if cat!='layout':
                        add('warning',loc+' uses tabify_docks outside the layout section.','Semantic layout action in non-layout section','tabify_docks is a runtime layout action and should normally be stored in ui.layout.',cat,idx,item)
                    primary=_dock_ref_display(item.get('primary')); secondary=_dock_ref_display(item.get('secondary'))
                    if not primary:
                        add('error',loc+' is missing primary dock reference.','Missing primary dock','tabify_docks requires a primary dock reference, such as "Model".',cat,idx,item)
                    if not secondary:
                        add('error',loc+' is missing secondary dock reference.','Missing secondary dock','tabify_docks requires a secondary dock reference, such as "Tasks".',cat,idx,item)
                    if primary and secondary and primary.casefold()==secondary.casefold():
                        add('error',loc+' references the same dock twice.','Invalid dock pair','primary and secondary must identify two different dock widgets.',cat,idx,item)
                    active=item.get('active','')
                    if active not in ('',None):
                        active_text=_dock_ref_display(active)
                        allowed_active={primary.casefold(),secondary.casefold(),'primary','secondary'} if primary and secondary else {'primary','secondary'}
                        if active_text and active_text.casefold() not in allowed_active:
                            add('warning',loc+' active dock does not match primary or secondary.','Unrecognized active dock','The active value should normally be "primary", "secondary", or one of the two dock references.',cat,idx,item)
                else:
                    target_path=str(item.get('path','') or '').strip()
                    if not target_path:
                        add('error',loc+' is missing path.','Missing target path','This instruction cannot be applied because it has no FreeCAD parameter path.',cat,idx,item)
                key=_instruction_key(item)
                if key in seen:
                    prev=seen[key]
                    prev_item=prev['item'];prev_loc='{} instruction {}'.format(prev['category'],prev['index'])
                    name_now=str(item.get('name','') or '')
                    name_prev=str(prev_item.get('name','') or '')
                    path_now=str(item.get('path','') or '')
                    path_prev=str(prev_item.get('path','') or '')
                    if path_now==path_prev and name_now==name_prev:
                        why='Both blocks address exactly the same target path and parameter name. Keeping both can make the intended final value ambiguous.'
                    elif path_now.lower()==path_prev.lower() and name_now.lower()==name_prev.lower():
                        diffs=[]
                        if path_now!=path_prev:diffs.append('path capitalization')
                        if name_now!=name_prev:diffs.append('name capitalization')
                        why='These blocks resolve to the same target when compared case-insensitively, but differ only in {}. Review whether FreeCAD should really contain both variants.'.format(' and '.join(diffs) or 'capitalization')
                    else:
                        why='Both blocks resolve to the same normalized FreeCAD target. One may override or conflict with the other.'
                    counterpart={'category':prev['category'],'index':prev['index'],'instruction':prev_item,'target':_instruction_target_text(prev_item)}
                    add('error','Duplicate instruction target: {} (also in {}).'.format(loc,prev_loc),'Duplicate instruction target',why,cat,idx,item,counterpart)
                else:
                    seen[key]={'category':cat,'index':idx,'item':item}
                if action in {'set','remove'}:
                    name=str(item.get('name','') or '').strip()
                    if not name:
                        add('error',loc+' is missing name.','Missing parameter name','A set/remove instruction requires the FreeCAD parameter name it should modify.',cat,idx,item)
                    if action=='set':
                        typ=str(item.get('type','') or '')
                        if typ not in allowed_types:
                            add('warning',loc+' uses unknown parameter type '+repr(typ)+'.','Unknown parameter type','The parameter type is not one of the standard FreeCAD types recognized by External Theme Creator. Verify that the type is valid for this FreeCAD version.',cat,idx,item)
                        if 'value' not in item:
                            add('error',loc+' is missing value.','Missing parameter value','A set instruction must include the value to write.',cat,idx,item)
                elif action=='set_toolbar':
                    tbitems=item.get('items')
                    if not isinstance(tbitems,list):
                        add('error',loc+' must contain an items list.','Invalid toolbar block','A set_toolbar instruction must contain an ordered items list.',cat,idx,item)
                    else:
                        seen_names={}
                        for j,entry in enumerate(tbitems,1):
                            if not isinstance(entry,dict):
                                add('error',loc+' toolbar item {} is not an object.'.format(j),'Invalid toolbar item','Toolbar item {} is not a JSON object. The toolbar instruction cannot be reconstructed reliably.'.format(j),cat,idx,item)
                                continue
                            ename=str(entry.get('name','') or '').strip();etype=str(entry.get('type','') or '')
                            if not ename:
                                add('error',loc+' toolbar item {} is missing name.'.format(j),'Missing toolbar item name','Toolbar item {} needs a name. Toolbar item order is preserved and will not be automatically reordered.'.format(j),cat,idx,item)
                            elif ename.lower() in seen_names:
                                first=seen_names[ename.lower()]
                                add('error',loc+' contains duplicate toolbar item name '+repr(ename)+'.','Duplicate toolbar item','Toolbar items {} and {} use the same name (case-insensitive). Toolbar item order is significant, so review which entry should remain.'.format(first,j),cat,idx,item)
                            else:seen_names[ename.lower()]=j
                            if etype not in allowed_types:
                                add('warning',loc+' toolbar item {} uses unknown parameter type {}.'.format(j,repr(etype)),'Unknown toolbar item type','Toolbar item {} uses a parameter type External Theme Creator does not recognize.'.format(j),cat,idx,item)
                            if 'value' not in entry:
                                add('error',loc+' toolbar item {} is missing value.'.format(j),'Missing toolbar item value','Toolbar item {} has no value and cannot be recreated reliably.'.format(j),cat,idx,item)
                if 'reason' in item:
                    add('warning',loc+' contains obsolete reason metadata; remove it to keep the standard instruction format.','Obsolete reason metadata','The reason field is not part of the standard instruction block format used by External Theme Creator and should be removed.',cat,idx,item)
                # Portability scan. Only the instruction value can meaningfully
                # contain a filesystem/environment dependency; path/name are FreeCAD
                # parameter identifiers, not OS paths. Known Qt serialized UI state
                # is reported separately and is never fed to path detection.
                if action=='set' and 'value' in item:
                    v=item.get('value')
                    iname=str(item.get('name','') or '')
                    if _serialized_ui_state(iname,v):
                        add('portability',
                            '{} contains serialized Qt/FreeCAD UI state.'.format(loc),
                            'Serialized UI state',
                            'This value is an opaque serialized window/dock/toolbar layout. It does not contain a detected OS filesystem path, but it can depend on the FreeCAD/Qt version, available dock widgets/toolbars, and screen/layout context.',
                            cat,idx,item)
                    else:
                        dep=_portable_value_dependency(v)
                        if dep:
                            kind,detail=dep
                            add('portability',
                                '{} contains a {} in value.'.format(loc,kind),
                                kind,
                                detail+' Theme packages should avoid machine-specific filesystem/environment dependencies when possible.',
                                cat,idx,item)
        info.append('Instruction count: '+str(total))
    def uniq(seq):
        out=[];seen_local=set()
        for x in seq:
            if x not in seen_local:seen_local.add(x);out.append(x)
        return out
    errors,warnings,portability=map(uniq,(errors,warnings,portability))
    if not errors:
        data=_write_theme_configuration(path,data)
        info.append('Instructions were organized by section and target, and JSON formatting was normalized.')
    return data,errors,warnings,portability,info,issues

def _configured_theme_cfg_path():
    folder=_theme_folder_for_cfg_tools()
    cfgname=_configured_cfg_filename_for_instructions(folder)
    if not _valid_cfg_filename(cfgname):
        raise LauncherError('The configured .cfg filename is missing or invalid. Open Develop theme → Settings and set it first.')
    return folder,(folder/cfgname).resolve(),cfgname

def _organize_cfg_xml(cfg):
    tree=ET.parse(cfg);root=tree.getroot()
    def walk(node,path=''):
        groups=[c for c in list(node) if c.tag=='FCParamGroup']
        for g in groups:
            name=str(g.attrib.get('Name',''))
            walk(g,(path+'/'+name).strip('/'))
        low=path.lower()
        # Toolbar parameter order can be meaningful. Never reorder inside toolbar groups.
        if 'toolbar' in low:return
        positions=[i for i,c in enumerate(list(node)) if c.tag=='FCParamGroup']
        if len(positions)>1:
            children=list(node); ordered=sorted((children[i] for i in positions),key=lambda c:str(c.attrib.get('Name','')).lower())
            for pos,g in zip(positions,ordered):children[pos]=g
            node[:]=children
    walk(root,'')
    try:ET.indent(tree,space='  ')
    except Exception:pass
    tree.write(cfg,encoding='utf-8',xml_declaration=True)

def _cfg_validation_report(organize=True):
    folder,cfg,cfgname=_configured_theme_cfg_path()
    errors=[]; warnings=[]; portability=[]; info=[]
    top_cfgs=sorted(folder.glob('*.cfg'),key=lambda p:p.name.lower())
    if not cfg.is_file():errors.append('Configured CFG does not exist: '+str(cfg))
    other=[p.name for p in top_cfgs if p.resolve()!=cfg]
    if other:warnings.append('Additional top-level .cfg file(s) found: '+', '.join(other)+'. The configured filename is authoritative; extra CFG files can cause ambiguity.')
    if not cfg.is_file():return folder,cfg,errors,warnings,portability,info
    try:tree=ET.parse(cfg); root=tree.getroot()
    except ET.ParseError as exc:errors.append('XML syntax error: '+str(exc)); return folder,cfg,errors,warnings,portability,info
    except Exception as exc:errors.append('Could not read CFG: '+str(exc)); return folder,cfg,errors,warnings,portability,info
    if root.tag not in {'FCParameters','FCParamGroup'}:warnings.append('Unexpected XML root element <{}>. FreeCAD user.cfg normally uses <FCParameters>.'.format(root.tag))
    allowed={'FCParamGroup','FCBool','FCInt','FCUInt','FCFloat','FCString','FCText'}
    transient_names={'geometry','windowstaterestored','maximized','fileopensavepath','recentfiles','lastmodule','lasttabindex','wsposition','overlayactivestylesheet'}
    def walk(parent,path=''):
        seen_groups=set();seen_params=set()
        for child in list(parent):
            tag=child.tag;name=str(child.attrib.get('Name','')).strip();here=(path+'/'+name).strip('/') if name else path
            if tag not in allowed:warnings.append('Unknown parameter node type <{}> at {}.'.format(tag,here or '<root>'))
            if tag=='FCParamGroup':
                if not name:errors.append('FCParamGroup without Name under '+(path or '<root>'))
                key=name.lower()
                if key in seen_groups:errors.append('Duplicate group Name "{}" under {}.'.format(name,path or '<root>'))
                seen_groups.add(key);walk(child,here);continue
            if not name:errors.append('{} without Name under {}.'.format(tag,path or '<root>'))
            key=name.lower()
            if key in seen_params:errors.append('Duplicate parameter Name "{}" under {}.'.format(name,path or '<root>'))
            seen_params.add(key)
            value=child.text if tag=='FCText' else child.attrib.get('Value','');value='' if value is None else str(value)
            if tag=='FCBool' and value.lower() not in {'0','1','true','false'}:errors.append('Invalid boolean value for {}/{}: {!r}'.format(path,name,value))
            elif tag in {'FCInt','FCUInt'}:
                try:
                    n=int(value,0)
                    if tag=='FCUInt' and n<0:raise ValueError
                except Exception:errors.append('Invalid integer value for {}/{}: {!r}'.format(path,name,value))
            elif tag=='FCFloat':
                try:float(value)
                except Exception:errors.append('Invalid floating-point value for {}/{}: {!r}'.format(path,name,value))
            lname=name.lower()
            if lname in transient_names or any(x in lname for x in ('recentfile','lastpath','lastdirectory')):
                portability.append('Transient/session-specific setting: {}/{}'.format(path,name))
            if 'stylesheet' in lname:
                portability.append('Stylesheet content embedded in CFG at {}/{}; theme QSS should normally remain external.'.format(path,name))
            if _serialized_ui_state(name,value):
                portability.append('Serialized UI state at {}/{}; no OS filesystem path detected. This opaque Qt/FreeCAD layout may depend on application version, available UI objects, or screen/layout context.'.format(path,name))
            else:
                dep=_portable_value_dependency(value)
                if dep:
                    kind,detail=dep
                    portability.append('{} at {}/{} = {!r}'.format(kind,path,name,value[:240]))
                # For fields explicitly named as path/directory/filename, catch other
                # absolute paths conservatively without treating arbitrary '/' as a path.
                if any(t in lname for t in ('path','directory','filename')) and value and not dep:
                    v=str(value).strip()
                    if re.match(r'(?i)^[a-z]:[\\/]',v) or v.startswith('\\\\') or re.match(r'^/(?:Users|home|tmp|var/tmp|Applications|Library|usr|opt|etc)(?:/|$)',v):
                        portability.append('Absolute filesystem path at {}/{} = {!r}'.format(path,name,value[:240]))
            if len(value)>512 and not _serialized_ui_state(name,value):
                warnings.append('Large/serialized value ({} chars) at {}/{}; verify portability before distributing.'.format(len(value),path,name))
    walk(root,'')
    def uniq(seq):
        out=[];seen=set()
        for x in seq:
            if x not in seen:seen.add(x);out.append(x)
        return out
    errors,warnings,portability=map(uniq,(errors,warnings,portability))
    info.append('Configured filename: '+cfgname)
    info.append('XML parsed successfully.' if not errors else 'XML parsed with structural/value errors listed below.')
    info.append('Top-level CFG files found: '+str(len(top_cfgs)))
    if organize and not errors:
        try:_organize_cfg_xml(cfg);info.append('CFG group sections were organized and XML formatting was normalized. Order-sensitive toolbar parameter entries were preserved.')
        except Exception as exc:warnings.append('CFG could not be reorganized: '+str(exc))
    return folder,cfg,errors,warnings,portability,info


_COLOR_HINT_RE=re.compile(r'(?:color|colour|background|foreground|highlight|selection|accent)',re.I)

def _instruction_color_info(item):
    """Return (QColor, storage_mode) for likely color instructions, else None."""
    if not isinstance(item,dict):return None
    name=str(item.get('name','') or '')
    path=str(item.get('path','') or '')
    if not _COLOR_HINT_RE.search(name+' '+path):return None
    raw=str(item.get('value','') or '').strip()
    typ=str(item.get('type','') or '').strip().lower()
    try:
        if raw.startswith('#'):
            h=raw[1:]
            if len(h)==6:
                r,g,b=int(h[0:2],16),int(h[2:4],16),int(h[4:6],16)
                return QtGui.QColor(r,g,b,255),('hex6',)
            if len(h)==8:
                r,g,b,a=int(h[0:2],16),int(h[2:4],16),int(h[4:6],16),int(h[6:8],16)
                return QtGui.QColor(r,g,b,a),('hex8',)
        if ',' in raw:
            vals=[int(x.strip()) for x in raw.split(',')]
            if len(vals) in (3,4) and all(0<=x<=255 for x in vals):
                if len(vals)==3: vals.append(255)
                return QtGui.QColor(*vals),('csv',len(raw.split(',')))
        if typ=='fcuint' or re.fullmatch(r'(?:0x[0-9a-f]+|\d+)',raw,re.I):
            n=int(raw,0)&0xffffffff
            # FreeCAD preference colors are conventionally packed RRGGBBAA.
            r=(n>>24)&0xff;g=(n>>16)&0xff;b=(n>>8)&0xff;a=n&0xff
            return QtGui.QColor(r,g,b,a),('fcuint_hex' if raw.lower().startswith('0x') else 'fcuint_dec',)
    except Exception:
        return None
    return None

def _set_instruction_color(item,color,mode):
    r,g,b,a=color.red(),color.green(),color.blue(),color.alpha()
    kind=mode[0] if mode else 'fcuint_dec'
    if kind=='hex6':item['value']='#{:02x}{:02x}{:02x}'.format(r,g,b)
    elif kind=='hex8':item['value']='#{:02x}{:02x}{:02x}{:02x}'.format(r,g,b,a)
    elif kind=='csv':
        item['value']='{}, {}, {}'.format(r,g,b) if len(mode)>1 and mode[1]==3 else '{}, {}, {}, {}'.format(r,g,b,a)
    else:
        n=((r&255)<<24)|((g&255)<<16)|((b&255)<<8)|(a&255)
        item['value']=('0x{:08X}'.format(n) if kind=='fcuint_hex' else str(n))
    return item

SWATCH_X_OFFSET = 6
_SWATCH_SLOT_ICON = None

def _swatch_slot_icon(size=20):
    # Transparent decoration used only to reserve the normal 20x20 QList icon
    # slot. The color swatch itself is painted directly by the item delegate so
    # its border is not raster-scaled by QIcon on high-DPI displays.
    global _SWATCH_SLOT_ICON
    if _SWATCH_SLOT_ICON is None:
        pm=QtGui.QPixmap(size,size);pm.fill(QtCore.Qt.transparent)
        _SWATCH_SLOT_ICON=QtGui.QIcon(pm)
    return _SWATCH_SLOT_ICON

class CaptureSwatchDelegate(QtWidgets.QStyledItemDelegate):
    """Paint capture color swatches directly in device space.

    A zero-width cosmetic pen is always one device pixel in Qt, regardless of
    Windows/macOS/Linux display scaling. This avoids the visually heavy border
    produced when a pre-rendered QPixmap/QIcon is scaled by the item view.
    """
    def paint(self,painter,option,index):
        super().paint(painter,option,index)
        meta=index.data(QtCore.Qt.UserRole)
        if not isinstance(meta,dict) or not meta.get('color_mode'):
            return
        instruction=meta.get('instruction')
        if not isinstance(instruction,dict):
            return
        cinfo=_instruction_color_info(instruction)
        if not cinfo:
            return
        color,_mode=cinfo

        opt=QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt,index)
        widget=getattr(opt,'widget',None)
        style=widget.style() if widget is not None else QtWidgets.QApplication.style()
        try:
            se=QtWidgets.QStyle.SE_ItemViewItemDecoration
        except AttributeError:
            se=QtWidgets.QStyle.SubElement.SE_ItemViewItemDecoration
        deco=style.subElementRect(se,opt,widget)
        if not deco.isValid() or deco.width()<=0 or deco.height()<=0:
            # Fallback for styles that do not expose the decoration sub-rect.
            deco=QtCore.QRect(option.rect.left()+4,option.rect.center().y()-10,20,20)

        # 18x18 visible square centered in the existing 20x20 icon slot.
        rect=QtCore.QRectF(
            deco.center().x()-9.0+SWATCH_X_OFFSET,
            deco.center().y()-9.0,
            18.0,18.0
        )
        painter.save()
        try:
            painter.setRenderHint(QtGui.QPainter.Antialiasing,True)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(color))
            painter.drawRoundedRect(rect,3.0,3.0)

            # Width 0 + cosmetic=True means exactly one physical device pixel.
            # Paint the border separately so only the rounded edge is
            # antialiased; the whole swatch is never resampled as an icon.
            pen=QtGui.QPen(QtGui.QColor(110,110,110))
            pen.setWidth(0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(rect,3.0,3.0)
        finally:
            painter.restore()

class CaptureListWidget(QtWidgets.QListWidget):
    """Selectable capture list with copy context menu and clickable color swatches."""
    def __init__(self,parent=None,color_editor=None,value_editor=None):
        super().__init__(parent)
        self._color_editor=color_editor
        self._value_editor=value_editor
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True);self.setUniformItemSizes(False)
        self.setIconSize(QtCore.QSize(20,20))
        self.setItemDelegate(CaptureSwatchDelegate(self))
        self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        self.setToolTip('Select blocks normally; Ctrl selects multiple blocks and Shift selects a range. Right-click for Copy/Edit value; double-click a block to edit its value.')
        self.itemDoubleClicked.connect(self._edit_value_item)
    def contextMenuEvent(self,event):
        item=self.itemAt(event.pos())
        if item is None:return
        menu=QtWidgets.QMenu(self);act_copy=menu.addAction('Copy')
        meta=item.data(QtCore.Qt.UserRole);instruction=(meta.get('instruction') if isinstance(meta,dict) else None)
        act_edit=None
        if isinstance(instruction,dict) and 'value' in instruction and str(instruction.get('action','')).lower()=='set':
            act_edit=menu.addAction('Edit value…')
        chosen=menu.exec(event.globalPos())
        if chosen is act_edit:
            if callable(self._value_editor):self._value_editor(item)
            return
        if chosen is not act_copy:return
        items=self.selectedItems() if item.isSelected() else [item]
        items=sorted(items,key=lambda x:self.row(x))
        blocks=[]
        for li in items:
            meta=li.data(QtCore.Qt.UserRole)
            if isinstance(meta,dict) and isinstance(meta.get('instruction'),dict):
                blocks.append(json.dumps(meta['instruction'],indent=2,ensure_ascii=False))
        if blocks:QtWidgets.QApplication.clipboard().setText('\n\n'.join(blocks))
    def _edit_value_item(self,item):
        if callable(self._value_editor):self._value_editor(item)
    def mousePressEvent(self,event):
        item=self.itemAt(event.pos())
        if item is not None and event.button()==QtCore.Qt.LeftButton:
            meta=item.data(QtCore.Qt.UserRole)
            if isinstance(meta,dict) and meta.get('color_mode'):
                rect=self.visualItemRect(item)
                if event.pos().x()<=rect.left()+self.iconSize().width()+12:
                    if callable(self._color_editor):self._color_editor(item)
                    event.accept();return
        super().mousePressEvent(event)

class CompareCFGDialog(QtWidgets.QDialog):
    def __init__(self,parent,instructions_filename,cfg_filename):
        super().__init__(parent)
        self.setWindowTitle('Compare and generate CFG instructions')
        self.resize(720,180)
        self.instructions_filename=instructions_filename
        self.cfg_filename=cfg_filename
        v=QtWidgets.QVBoxLayout(self)
        self.old=PathRow('Old CFG',False,'FreeCAD CFG (*.cfg);;All files (*)',drop_exts={'.cfg'})
        self.new=PathRow('New CFG',False,'FreeCAD CFG (*.cfg);;All files (*)',drop_exts={'.cfg'})
        v.addWidget(self.old);v.addWidget(self.new)
        h=QtWidgets.QHBoxLayout();h.addStretch()
        b=QtWidgets.QPushButton('Compare and generate');b.clicked.connect(self.generate);h.addWidget(b);v.addLayout(h)
    def generate(self):
        try:
            old=Path(self.old.edit.text()).expanduser().resolve();new=Path(self.new.edit.text()).expanduser().resolve()
            if not old.is_file() or old.suffix.lower()!='.cfg':raise LauncherError('Select a valid Old CFG file.')
            if not new.is_file() or new.suffix.lower()!='.cfg':raise LauncherError('Select a valid New CFG file.')
            folder=_theme_folder_for_cfg_tools()
            requested=_instructions_json_path(folder,self.instructions_filename)
            existing=[p.name for p in (folder/CONFIG_NAME,folder/SKIPPED_NAME) if p.exists()]
            if requested.exists() and requested.name not in existing:existing.append(requested.name)
            if existing:
                raise LauncherError(
                    'Compare and generate CFG instructions cannot overwrite existing JSON files.\n\n'
                    'The following file(s) already exist in the Theme Folder:\n'
                    + "\n".join(existing)
                    + '\n\nYour existing instructions have not been changed. '
                      'To generate new instructions, use an empty Theme Folder or '
                      'move/rename the existing JSON files first.')
            cfgname=_set_configured_cfg_filename(self.cfg_filename,folder,sync_json=False)
            configuration,skipped=_generate_cfg_exact(old,new,cfgname,folder)
            standard=folder/CONFIG_NAME
            if requested.resolve()!=standard.resolve() and standard.exists():standard.replace(requested)
            info('CFG instructions generated successfully.\n\n'+str(requested)+'\n'+str(folder/SKIPPED_NAME))
            self.accept()
        except Exception as exc:error(str(exc))

class ValidationIssuesDialog(QtWidgets.QDialog):
    """Interactive validation results for theme-configuration.json.

    Each issue is a selectable row. Instruction-level problems expose the exact
    JSON block below the issue list and can be removed directly from the source
    file. Duplicate-target rows also expose the earlier matching block so the
    creator can choose which side of the duplicate pair to delete.
    """
    def __init__(self,path,parent=None):
        super().__init__(parent or mw())
        self.path=Path(path)
        self.setWindowTitle('Validate CFG instructions')
        self.resize(1120,720)
        v=QtWidgets.QVBoxLayout(self)
        self.summary=QtWidgets.QLabel();self.summary.setWordWrap(True);v.addWidget(self.summary)
        self.tree=QtWidgets.QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(['Severity / problem','Location','Target','Why this is a problem','Action'])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tree.setWordWrap(True)
        try:
            hdr=self.tree.header()
            hdr.setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch)
            hdr.setSectionResizeMode(3,QtWidgets.QHeaderView.Stretch)
            hdr.setSectionResizeMode(4,QtWidgets.QHeaderView.ResizeToContents)
        except Exception:pass
        self.tree.currentItemChanged.connect(self._selection_changed)
        v.addWidget(self.tree,1)
        preview_label=QtWidgets.QLabel('Selected problem block')
        v.addWidget(preview_label)
        self.preview=QtWidgets.QPlainTextEdit();self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.preview.setMinimumHeight(210)
        try:self.preview.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        except Exception:pass
        v.addWidget(self.preview)
        h=QtWidgets.QHBoxLayout();self.info_label=QtWidgets.QLabel();self.info_label.setWordWrap(True);h.addWidget(self.info_label,1)
        close=QtWidgets.QPushButton('Close');close.clicked.connect(self.accept);h.addWidget(close);v.addLayout(h)
        self.refresh()
    def _severity_label(self,severity):
        return {'error':'ERROR','warning':'WARNING','portability':'PORTABILITY'}.get(str(severity),str(severity).upper())
    def _location(self,issue):
        cat=issue.get('category');idx=issue.get('index')
        if cat is not None and idx is not None:return '{} #{}'.format(cat,idx)
        if cat is not None:return str(cat)
        return 'File / schema'
    def _issue_payload(self,issue,which='primary'):
        if which=='counterpart':
            cp=issue.get('counterpart') or {}
            return cp.get('category'),cp.get('index'),cp.get('instruction')
        return issue.get('category'),issue.get('index'),issue.get('instruction')
    def _target(self,issue):
        return str(issue.get('target') or '')
    def refresh(self):
        try:
            data,errors,warnings,portability,infos,issues=_validate_theme_configuration_file(self.path)
        except Exception as exc:
            self.summary.setText('Validation failed: '+str(exc));self.tree.clear();self.preview.clear();return
        self._issues=issues;self._infos=infos
        self.summary.setText(
            'File: {}\nSummary: {} error(s), {} warning(s), {} portability note(s). '
            'Select a problem to inspect its exact JSON block. Delete removes that instruction directly from the file.'.format(
                self.path,len(errors),len(warnings),len(portability)
            )
        )
        self.info_label.setText('  '.join(infos or []))
        self.tree.clear()
        first=None
        for issue in issues:
            sev=self._severity_label(issue.get('severity'))
            top=QtWidgets.QTreeWidgetItem([
                sev+' — '+str(issue.get('title') or 'Problem'),
                self._location(issue),
                self._target(issue),
                str(issue.get('explanation') or ''),
                ''
            ])
            top.setData(0,QtCore.Qt.UserRole,{'issue':issue,'which':'primary'})
            self.tree.addTopLevelItem(top)
            if first is None:first=top
            if isinstance(issue.get('instruction'),dict) and issue.get('category') is not None and issue.get('index') is not None:
                holder=QtWidgets.QWidget();hl=QtWidgets.QHBoxLayout(holder);hl.setContentsMargins(0,0,0,0)
                b=QtWidgets.QPushButton('Delete')
                b.setToolTip('Delete this problematic instruction block from theme-configuration.json.')
                b.clicked.connect(lambda checked=False,i=issue:self._delete_issue_block(i,'primary'))
                hl.addWidget(b)
                self.tree.setItemWidget(top,4,holder)
            cp=issue.get('counterpart')
            if isinstance(cp,dict) and isinstance(cp.get('instruction'),dict):
                child=QtWidgets.QTreeWidgetItem([
                    'Duplicate counterpart',
                    '{} #{}'.format(cp.get('category'),cp.get('index')),
                    str(cp.get('target') or _instruction_target_text(cp.get('instruction'))),
                    'This is the other instruction involved in the duplicate/conflict. Select it to inspect its block or delete it instead.',
                    ''
                ])
                child.setData(0,QtCore.Qt.UserRole,{'issue':issue,'which':'counterpart'})
                top.addChild(child);top.setExpanded(True)
                holder2=QtWidgets.QWidget();hl2=QtWidgets.QHBoxLayout(holder2);hl2.setContentsMargins(0,0,0,0)
                b2=QtWidgets.QPushButton('Delete')
                b2.setToolTip('Delete the duplicate counterpart block instead of the primary block.')
                b2.clicked.connect(lambda checked=False,i=issue:self._delete_issue_block(i,'counterpart'))
                hl2.addWidget(b2)
                self.tree.setItemWidget(child,4,holder2)
        if first is not None:
            self.tree.setCurrentItem(first);self._selection_changed(first,None)
        else:
            self.preview.setPlainText('No validation problems detected.')
    def _selection_changed(self,current,previous):
        if current is None:self.preview.clear();return
        meta=current.data(0,QtCore.Qt.UserRole)
        if not isinstance(meta,dict):self.preview.clear();return
        issue=meta.get('issue') or {};which=meta.get('which','primary')
        cat,idx,item=self._issue_payload(issue,which)
        if not isinstance(item,dict):
            self.preview.setPlainText(str(issue.get('explanation') or ''))
            return
        header='Location: {} #{}\nTarget: {}\n\n'.format(cat,idx,_instruction_target_text(item))
        self.preview.setPlainText(header+json.dumps(item,indent=2,ensure_ascii=False))
    def _delete_issue_block(self,issue,which='primary'):
        cat,idx,item=self._issue_payload(issue,which)
        if not (cat is not None and idx is not None and isinstance(item,dict)):
            return
        loc='{} #{}'.format(cat,idx)
        target=_instruction_target_text(item)
        reply=QtWidgets.QMessageBox.question(
            self,'Delete CFG instruction',
            'Delete this instruction block from theme-configuration.json?\n\n{}\n{}'.format(loc,target),
            QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if reply!=QtWidgets.QMessageBox.Yes:return
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            items=((data.get('ui') or {}).get(cat)) if isinstance(data,dict) else None
            if not isinstance(items,list):raise LauncherError('The instruction section no longer exists. Re-run validation.')
            pos=int(idx)-1
            if not (0<=pos<len(items)) or items[pos]!=item:
                matches=[i for i,v in enumerate(items) if v==item]
                if len(matches)==1:pos=matches[0]
                else:raise LauncherError('The JSON file changed after validation. Close and reopen Validate CFG instructions before deleting this block.')
            del items[pos]
            # Preserve the current human-edited ordering while removing the chosen
            # block. A subsequent successful validation can organize/normalize it.
            self.path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
            self.refresh()
        except Exception as exc:error(str(exc))


class CFGDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(mw())
        self.setWindowTitle('CFG Instructions')
        self.resize(900,650)
        self._capture_timer=QtCore.QTimer(self);self._capture_timer.setInterval(500);self._capture_timer.timeout.connect(self._capture_poll)
        self._capture_last_hash=None;self._capture_last_cfg=None;self._capture_changes=0
        self._capture_configuration=None;self._capture_skipped=None
        self._capture_item_index={}
        v=QtWidgets.QVBoxLayout(self)
        r=QtWidgets.QHBoxLayout();r.addWidget(QtWidgets.QLabel('CFG instructions filename (.json)'))
        self.name=QtWidgets.QLineEdit(CONFIG_NAME);r.addWidget(self.name,1);v.addLayout(r)
        r2=QtWidgets.QHBoxLayout();r2.addWidget(QtWidgets.QLabel('CFG filename (.cfg)'))
        try: default_cfgname=_configured_cfg_filename_for_instructions(_theme_folder_for_cfg_tools())
        except Exception:
            default_cfgname=str(_load_runtime_settings().get('creator_cfg_filename','') or params().GetString(CFG_FILENAME_KEY,'') or 'FreeCAD Theme.cfg').strip()
        if not _valid_cfg_filename(default_cfgname):default_cfgname='FreeCAD Theme.cfg'
        self.cfgname=QtWidgets.QLineEdit(default_cfgname);self.cfgname.setToolTip('Filename only, ending in .cfg. This is written to theme-configuration.json output.filename and is used when External Theme Creator must create a missing Theme Folder CFG.')
        self.cfgname.editingFinished.connect(self._cfg_filename_edited)
        r2.addWidget(self.cfgname,1);v.addLayout(r2)
        top=QtWidgets.QGridLayout();v.addLayout(top)
        buttons=[
            ('Compare and generate CFG instructions (.json)',self.open_compare),
            ('Generate blank CFG instructions (.json)',self.generate_blank),
            ('Validate CFG instructions (.json)',self.validate_instructions),
            ('Validate CFG (.cfg)',self.validate_theme_cfg),
        ]
        for i,(text,fn) in enumerate(buttons):
            b=QtWidgets.QPushButton(text);b.clicked.connect(fn);top.addWidget(b,i//2,i%2)
        line=QtWidgets.QFrame();line.setFrameShape(QtWidgets.QFrame.HLine);v.addWidget(line)
        h=QtWidgets.QHBoxLayout()
        self.start=QtWidgets.QPushButton('Start capture');self.stop=QtWidgets.QPushButton('Stop capture');self.stop.setEnabled(False);self.clear_captured=QtWidgets.QPushButton('Clear captured')
        self.start.clicked.connect(self.capture_start);self.stop.clicked.connect(self.capture_stop);self.clear_captured.clicked.connect(self.clear_captured_blocks)
        self.add_selection=QtWidgets.QPushButton('Add selection to the CFG instructions');self.add_selection.clicked.connect(self.add_selected_instructions)
        h.addWidget(self.start);h.addWidget(self.stop);h.addWidget(self.clear_captured);h.addStretch();h.addWidget(self.add_selection);v.addLayout(h)
        self.capture_status=QtWidgets.QLabel('Capture inactive.');v.addWidget(self.capture_status)
        self.out=CaptureListWidget(self,self._edit_capture_color,self._edit_capture_value)
        v.addWidget(self.out,1)
    def _instructions_filename(self):
        return str(self.name.text().strip() or CONFIG_NAME)
    def _cfg_filename(self, sync_json=True):
        folder=_theme_folder_for_cfg_tools()
        return _set_configured_cfg_filename(self.cfgname.text(),folder,sync_json=sync_json)
    def _cfg_filename_edited(self):
        try:self._cfg_filename(sync_json=True)
        except Exception as exc:error(str(exc))
    def open_compare(self):
        try:
            _instructions_json_path(_theme_folder_for_cfg_tools(),self._instructions_filename())
            cfgname=self._cfg_filename(sync_json=True)
        except Exception as exc:return error(str(exc))
        CompareCFGDialog(self,self._instructions_filename(),cfgname).exec()
    def generate_blank(self):
        try:
            folder=_theme_folder_for_cfg_tools();target=folder/CONFIG_NAME
            if target.exists():raise LauncherError('A theme-configuration.json file already exists in the Theme Folder. Remove it before generating a blank CFG instructions file.')
            requested=_instructions_json_path(folder,self._instructions_filename())
            if requested.exists():raise LauncherError('The requested CFG instructions file already exists. Remove it before continuing:\n'+str(requested))
            cfgname=self._cfg_filename(sync_json=False)
            _write_theme_configuration(requested,_blank_theme_configuration(cfgname))
            info('Blank CFG instructions file created:\n'+str(requested))
        except Exception as exc:error(str(exc))
    def validate_instructions(self):
        try:
            # Do not sync output.filename before validation. A malformed JSON file
            # must reach the repair-aware validator first; the sync helper itself
            # parses JSON strictly and would otherwise raise before repair can run.
            folder=_theme_folder_for_cfg_tools();self._cfg_filename(sync_json=False);path=folder/CONFIG_NAME
            ValidationIssuesDialog(path,self).exec()
        except Exception as exc:error(str(exc))
    def validate_theme_cfg(self):
        try:
            self._cfg_filename(sync_json=True)
            folder,cfg,errors,warnings,portability,infos=_cfg_validation_report(organize=True)
            lines=['CFG validation','', 'Theme Folder: '+str(folder),'CFG: '+str(cfg),'','Summary: {} error(s), {} warning(s), {} portability note(s).'.format(len(errors),len(warnings),len(portability))]
            if infos:lines += ['', 'Information:']+['• '+x for x in infos]
            if errors:lines += ['', 'Errors:']+['• '+x for x in errors]
            if warnings:lines += ['', 'Warnings:']+['• '+x for x in warnings]
            if portability:lines += ['', 'Portability notes:']+['• '+x for x in portability]
            if not errors and not warnings and not portability:lines += ['', 'No problems detected.']
            _show_text_dialog('Validate CFG','\n'.join(lines),self)
        except Exception as exc:error(str(exc))
    def _snapshot_current_cfg(self):
        _flush_user_parameters();src=_user_cfg()
        if not src.exists():raise LauncherError('Active user.cfg was not found at '+str(src))
        fd,name=tempfile.mkstemp(prefix='external-theme-creator-live-',suffix='.cfg');os.close(fd);dst=Path(name);shutil.copy2(src,dst);return dst
    def _capture_item_key(self,item):
        try:return repr(_instruction_key(item))
        except Exception:return json.dumps(item,sort_keys=True,ensure_ascii=False)
    def _render_capture_item(self,li,meta):
        item=_without_reason_fields(dict(meta.get('instruction') or {}));meta['instruction']=item
        text=json.dumps(item,indent=2,ensure_ascii=False);li.setText(text)
        font=QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont);li.setFont(font)
        fm=QtGui.QFontMetrics(font);lines=text.count('\n')+1;li.setSizeHint(QtCore.QSize(0,max(34,lines*fm.lineSpacing()+14)))
        cinfo=_instruction_color_info(item)
        if cinfo:
            color,mode=cinfo;meta['color_mode']=mode;li.setIcon(_swatch_slot_icon());li.setToolTip((('Skipped/review change: '+str(meta.get('source_category',''))+'; explicit selection will add it under other_ui. ') if meta.get('skipped') else 'Section: '+str(meta.get('category',''))+'. ')+'Click the color square to edit this value.')
        else:
            meta.pop('color_mode',None);li.setIcon(QtGui.QIcon());li.setToolTip(('Skipped/review change: '+str(meta.get('source_category',''))+'; explicit selection will add it under other_ui.') if meta.get('skipped') else 'Section: '+str(meta.get('category','')))
        li.setData(QtCore.Qt.UserRole,meta)
    def _populate_capture_blocks(self,configuration,skipped):
        # Merge into the persistent capture list. Stop/Start cycles intentionally
        # retain captured blocks until the creator presses Clear captured.
        self._capture_configuration=configuration;self._capture_skipped=skipped
        blocks=[]
        for cat,items in ((configuration.get('ui') or {}).items() if isinstance(configuration,dict) else []):
            for item in items or []:blocks.append((cat,item,False,cat))
        for skipcat,items in ((skipped.get('categories') or {}).items() if isinstance(skipped,dict) else []):
            for item in items or []:blocks.append(('other_ui',item,True,skipcat))
        for cat,item,is_skipped,source_cat in blocks:
            item=_without_reason_fields(item);key=self._capture_item_key(item)
            meta={'category':cat,'instruction':item,'skipped':is_skipped,'source_category':source_cat,'capture_key':key}
            li=self._capture_item_index.get(key)
            if li is None or self.out.row(li)<0:
                li=QtWidgets.QListWidgetItem();self.out.addItem(li);self._capture_item_index[key]=li
            self._render_capture_item(li,meta)
    def _edit_capture_value(self,li):
        meta=li.data(QtCore.Qt.UserRole)
        if not isinstance(meta,dict):return
        item=dict(meta.get('instruction') or {})
        if str(item.get('action','')).lower()!='set' or 'value' not in item:return
        old=str(item.get('value',''))
        typ=str(item.get('type','') or '')
        name=str(item.get('name','') or item.get('path','') or 'instruction')
        new,ok=QtWidgets.QInputDialog.getText(self,'Edit captured value','{} ({})'.format(name,typ or 'value'),QtWidgets.QLineEdit.Normal,old)
        if not ok:return
        new=str(new)
        try:
            if typ=='FCBool' and new.strip().lower() not in {'0','1','true','false'}:
                raise LauncherError('FCBool values must be 0, 1, true, or false.')
            if typ=='FCInt':int(new,0)
            if typ=='FCUInt':
                if int(new,0)<0:raise ValueError
            if typ=='FCFloat':float(new)
        except LauncherError as exc:return error(str(exc))
        except Exception:return error('The value is not valid for {}.'.format(typ or 'this parameter type'))
        item['value']=new;meta['instruction']=item
        self._render_capture_item(li,meta)

    def _edit_capture_color(self,li):
        meta=li.data(QtCore.Qt.UserRole)
        if not isinstance(meta,dict):return
        item=dict(meta.get('instruction') or {});cinfo=_instruction_color_info(item)
        if not cinfo:return
        initial,mode=cinfo
        opts=QtWidgets.QColorDialog.ShowAlphaChannel if hasattr(QtWidgets.QColorDialog,'ShowAlphaChannel') else QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel
        color=QtWidgets.QColorDialog.getColor(initial,self,'Select Color',opts)
        if not color.isValid():return
        _set_instruction_color(item,color,mode);meta['instruction']=item;meta['color_mode']=mode
        self._render_capture_item(li,meta)
    def clear_captured_blocks(self):
        global _capture_path
        self.out.clear();self._capture_item_index={};self._capture_configuration=None;self._capture_skipped=None;self._capture_changes=0
        # If capture is active, clear also becomes the new baseline so already
        # cleared differences do not immediately reappear on the next change.
        if self._capture_timer.isActive():
            try:
                snap=self._snapshot_current_cfg()
                if _capture_path and _capture_path.exists():_capture_path.unlink(missing_ok=True)
                _capture_path=snap;self._capture_last_hash=hashlib.sha256(snap.read_bytes()).hexdigest();self._capture_last_cfg=str(_user_cfg())
                self.capture_status.setText('Captured blocks cleared. Monitoring continues from the current configuration.')
            except Exception as exc:self.capture_status.setText('Capture clear error: '+str(exc))
        else:self.capture_status.setText('Captured blocks cleared.')
    def capture_start(self):
        global _capture_path
        if self._capture_timer.isActive():return
        try:
            self._cfg_filename(sync_json=True)
            snap=self._snapshot_current_cfg()
            if _capture_path and _capture_path.exists():_capture_path.unlink(missing_ok=True)
            _capture_path=snap;self._capture_last_hash=hashlib.sha256(snap.read_bytes()).hexdigest();self._capture_last_cfg=str(_user_cfg());self._capture_changes=0
            self.start.setEnabled(False);self.stop.setEnabled(True);self.capture_status.setText('Monitoring configuration changes in real time…');self._capture_timer.start()
        except Exception as exc:error(str(exc))
    def _capture_poll(self):
        global _capture_path
        if not _capture_path or not _capture_path.exists():self._capture_timer.stop();return
        current=None;outdir=None
        try:
            current=self._snapshot_current_cfg();digest=hashlib.sha256(current.read_bytes()).hexdigest()
            if digest==self._capture_last_hash:return
            self._capture_last_hash=digest;outdir=Path(tempfile.mkdtemp(prefix='external-theme-creator-capture-out-'))
            cfgname=self._cfg_filename(sync_json=True)
            a,s=_generate_cfg_exact(_capture_path,current,cfgname,outdir);self._capture_changes+=1;self._populate_capture_blocks(a,s)
            self.capture_status.setText('Change detected live — {} update{} observed. Monitoring continues…'.format(self._capture_changes,'' if self._capture_changes==1 else 's'))
        except Exception as exc:self.capture_status.setText('Capture monitor error: '+str(exc))
        finally:
            if current is not None:
                try:current.unlink(missing_ok=True)
                except Exception:pass
            if outdir is not None:shutil.rmtree(outdir,ignore_errors=True)
    def capture_stop(self):
        global _capture_path
        if not _capture_path or not _capture_path.exists():return error('No active capture. Press Start capture first.')
        try:self._capture_poll()
        finally:
            self._capture_timer.stop()
            try:_capture_path.unlink(missing_ok=True)
            except Exception:pass
            _capture_path=None;self.start.setEnabled(True);self.stop.setEnabled(False);self.capture_status.setText('Capture stopped. Select instruction blocks to add them to theme-configuration.json.')
    def add_selected_instructions(self):
        try:
            selected=self.out.selectedItems()
            if not selected:raise LauncherError('Select one or more captured instruction blocks first.')
            folder=_theme_folder_for_cfg_tools();target=folder/CONFIG_NAME
            # Save the selected captured instructions into an existing JSON file,
            # or start from the same schema as Generate blank CFG instructions.
            # Do not write a new file until the instruction merge succeeds.
            cfgname=self._cfg_filename(sync_json=True)
            created=not target.is_file()
            data=(_blank_theme_configuration(cfgname) if created
                  else json.loads(target.read_text(encoding='utf-8')))
            if not isinstance(data,dict):raise LauncherError('theme-configuration.json is not a JSON object.')
            data.setdefault('output',{})['filename']=cfgname
            ui=data.setdefault('ui',{})
            # Keep every normalized target so pre-existing ambiguities are not hidden.
            # _instruction_key() is deliberately case-insensitive because FreeCAD
            # parameter targets that differ only by capitalization should be
            # reviewed rather than silently duplicated.
            existing={}
            for cat,items in ui.items():
                if isinstance(items,list):
                    for item in items:
                        if isinstance(item,dict):existing.setdefault(_instruction_key(item),[]).append((cat,item))

            def exact_target_key(item):
                action=str(item.get('action','')).lower()
                if action in {'set_toolbar','remove_toolbar'}:
                    return ('toolbar',str(item.get('path','')))
                return ('param',str(item.get('path','')),str(item.get('name','')))

            added=0;updated=0;identical=0;conflicts=0
            for li in selected:
                meta=li.data(QtCore.Qt.UserRole)
                if not isinstance(meta,dict):continue
                item=dict(meta.get('instruction') or {});cat=str(meta.get('category') or 'other_ui')
                key=_instruction_key(item)
                matches=existing.get(key,[])
                if not matches:
                    ui.setdefault(cat,[]).append(item)
                    existing.setdefault(key,[]).append((cat,item))
                    added+=1
                    continue

                # More than one existing instruction already resolves to this
                # normalized target. Do not guess which one should be updated.
                if len(matches)!=1:
                    conflicts+=1
                    continue

                existing_cat,existing_item=matches[0]
                # If the spelling/capitalization differs, adding this block would
                # create the same ambiguity reported by Validate CFG instructions.
                if exact_target_key(existing_item)!=exact_target_key(item):
                    conflicts+=1
                    continue

                old_action=str(existing_item.get('action','')).lower()
                new_action=str(item.get('action','')).lower()
                if old_action!=new_action:
                    # set vs remove (or set_toolbar vs remove_toolbar) is a real
                    # semantic conflict, not a value update.
                    conflicts+=1
                    continue

                if existing_item==item:
                    identical+=1
                    continue

                # Exact same target/action with changed data: update the existing
                # instruction in place. This covers normal set value/type changes
                # and complete set_toolbar item-list changes while preserving the
                # instruction's position/section in the JSON file.
                existing_item.clear();existing_item.update(item)
                updated+=1

            _write_theme_configuration(target,data)
            parts=[]
            if created:parts.append('Created theme-configuration.json with the required structure.')
            if added:parts.append('Added {} selected instruction block{}.'.format(added,'' if added==1 else 's'))
            if updated:parts.append('Updated {} existing instruction block{} with the newly captured value{}.'.format(updated,'' if updated==1 else 's','' if updated==1 else 's'))
            if identical:parts.append('{} identical existing instruction block{} skipped.'.format(identical,'' if identical==1 else 's'))
            if conflicts:parts.append('{} duplicate/conflicting target{} were not added.'.format(conflicts,'' if conflicts==1 else 's'))
            if not parts:parts.append('No instruction blocks were added or updated.')
            info('\n\n'.join(parts))
        except Exception as exc:error(str(exc))
    def closeEvent(self,event):
        global _capture_path
        try:
            if _valid_cfg_filename(self.cfgname.text()):self._cfg_filename(sync_json=True)
        except Exception:pass
        try:self._capture_timer.stop()
        except Exception:pass
        if _capture_path:
            try:_capture_path.unlink(missing_ok=True)
            except Exception:pass
            _capture_path=None
        self.start.setEnabled(True);self.stop.setEnabled(False);super().closeEvent(event)

class LauncherError(Exception):
    pass


def _module_dir():
    return Path(__file__).resolve().parent


def _slugify_theme_id(theme_name):
    value=str(theme_name or '').strip().lower()
    value=re.sub(r'[^a-z0-9]+','_',value)
    return re.sub(r'_+','_',value).strip('_')


def _normalize_theme_package_value(value):
    raw=str(value or '').strip().lower()
    if raw in {THEME_PACKAGE_OPTION_ARTWORK_ONLY.lower(),THEME_PACKAGE_MODE_ARTWORK_ONLY}:
        return THEME_PACKAGE_OPTION_ARTWORK_ONLY
    return THEME_PACKAGE_OPTION_COMPLETE


def _theme_package_manifest_value(value):
    return THEME_PACKAGE_MODE_ARTWORK_ONLY if _normalize_theme_package_value(value)==THEME_PACKAGE_OPTION_ARTWORK_ONLY else THEME_PACKAGE_MODE_COMPLETE


def _is_artwork_only_theme_package(value):
    return _theme_package_manifest_value(value)==THEME_PACKAGE_MODE_ARTWORK_ONLY


def _canonical_manifest_bytes(manifest):
    return json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')


def _payload_fernet_key():
    return base64.urlsafe_b64encode(hashlib.sha256(b'External Theme Creator Theme Payload Key v1').digest())


def _require_crypto():
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
        return Fernet,serialization,Ed25519PrivateKey,Ed25519PublicKey
    except Exception as exc:
        try:
            if _tc_deps.ensure_current(mw()):
                from cryptography.fernet import Fernet
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
                return Fernet,serialization,Ed25519PrivateKey,Ed25519PublicKey
        except Exception as install_error:
            raise LauncherError(str(install_error)) from install_error
        raise LauncherError("cryptography installation was declined; signed-theme features require it.") from exc


def _load_author_private_key(private_key_path):
    Fernet,serialization,Ed25519PrivateKey,Ed25519PublicKey=_require_crypto()
    try:
        private_key=serialization.load_pem_private_key(Path(private_key_path).read_bytes(),password=None)
    except Exception as exc:
        raise LauncherError('Unable to read the selected Author Key as a PEM private key.') from exc
    if not isinstance(private_key,Ed25519PrivateKey):
        raise LauncherError('The selected Author Key is not an Ed25519 private key.')
    public_key=private_key.public_key()
    raw=public_key.public_bytes(encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)
    fingerprint_hex=raw.hex().upper()
    fingerprint='-'.join(fingerprint_hex[i:i+4] for i in range(0,min(len(fingerprint_hex),32),4))
    public_pem=public_key.public_bytes(encoding=serialization.Encoding.PEM,format=serialization.PublicFormat.SubjectPublicKeyInfo)
    return private_key,public_pem,fingerprint


def _encrypt_payload(payload_bytes):
    Fernet,serialization,Ed25519PrivateKey,Ed25519PublicKey=_require_crypto()
    return Fernet(_payload_fernet_key()).encrypt(payload_bytes)

def _decrypt_payload(payload_bytes):
    Fernet,serialization,Ed25519PrivateKey,Ed25519PublicKey=_require_crypto()
    try:
        return Fernet(_payload_fernet_key()).decrypt(payload_bytes)
    except Exception as exc:
        raise LauncherError('Theme payload could not be decrypted or is damaged.') from exc

def _verify_signature(manifest,public_pem,signature_b64):
    Fernet,serialization,Ed25519PrivateKey,Ed25519PublicKey=_require_crypto()
    try:
        public_key=serialization.load_pem_public_key(public_pem)
        if not isinstance(public_key,Ed25519PublicKey):
            raise LauncherError('Theme package public key is not an Ed25519 key.')
        public_key.verify(base64.b64decode(signature_b64),_canonical_manifest_bytes(manifest))
    except LauncherError:
        raise
    except Exception as exc:
        raise LauncherError('Theme package signature verification failed.') from exc

def _read_theme_package_full(path):
    path=Path(path).expanduser()
    if not path.is_file(): raise LauncherError('Theme file does not exist or is not a file.')
    with zipfile.ZipFile(path,'r') as z:
        names=set(z.namelist());required={'manifest.json','author_public_key.pem','signature.sig','payload.enc'};missing=sorted(required-names)
        if missing: raise LauncherError('Theme package is missing required files: '+', '.join(missing))
        manifest=json.loads(z.read('manifest.json').decode('utf-8'));pub=z.read('author_public_key.pem');sig=z.read('signature.sig').decode('ascii').strip();enc=z.read('payload.enc')
    _verify_signature(manifest,pub,sig)
    if manifest.get('schema_version')!=THEME_SCHEMA_VERSION or manifest.get('package_type')!=THEME_PACKAGE_TYPE:
        raise LauncherError('Selected file is not a supported External Theme Creator theme package.')
    if hashlib.sha256(enc).hexdigest()!=str(manifest.get('payload_hash_sha256','')):
        raise LauncherError('Theme package payload does not match the signed manifest.')
    return manifest,_decrypt_payload(enc)

def _theme_package_license_text(path):
    manifest,payload=_read_theme_package_full(path)
    license_text=''
    with zipfile.ZipFile(io.BytesIO(payload),'r') as z:
        for candidate in ('files/'+THEME_LICENSE_RELPATH,THEME_LICENSE_RELPATH,LICENSE_FILE_NAME,'files/'+LICENSE_FILE_NAME):
            if candidate in z.namelist():
                license_text=z.read(candidate).decode('utf-8',errors='replace');break
    return manifest,license_text


def _license_options():
    license_dir=_module_dir()/CC_LICENSES_DIR_NAME
    available={p.stem for p in license_dir.glob('*.lic') if p.is_file()}
    ordered=[name for name,spec in LICENSE_PRESET_DETAILS.items() if Path(spec["filename"]).stem in available]
    extras=sorted(available-{Path(spec["filename"]).stem for spec in LICENSE_PRESET_DETAILS.values()},key=str.lower)
    return ordered+extras+[CUSTOM_LICENSE_OPTION]


def _license_source_path(choice):
    if choice==CUSTOM_LICENSE_OPTION:return None
    details=LICENSE_PRESET_DETAILS.get(choice)
    name=details['filename'] if details else choice+'.lic'
    p=_module_dir()/CC_LICENSES_DIR_NAME/name
    return p if p.is_file() else None


def _default_license_brief(choice):
    return str(LICENSE_PRESET_DETAILS.get(choice,{}).get('brief',''))


def _is_safe_relpath(rel):
    if not rel or rel.startswith(('/', '\\')) or ':' in rel:return False
    p=Path(rel)
    return not p.is_absolute() and '..' not in p.parts


def _detect_splash_relpath(paths):
    if 'splash/freecadsplash.png' in paths:return 'splash/freecadsplash.png'
    preferred={'freecadsplash.png','splash_image.png'}
    exact=[rel for rel in paths if Path(rel).name.lower() in preferred]
    if exact:return sorted(exact,key=str.lower)[0]
    named=[rel for rel in paths if Path(rel).suffix.lower()=='.png' and 'splash' in Path(rel).stem.lower()]
    return sorted(named,key=str.lower)[0] if named else ''


def _count_suffixes(paths):
    counts={'.svg':0,'.png':0,'.qss':0,'.cfg':0}
    for rel in paths:
        suffix=Path(rel).suffix.lower()
        if suffix in counts:counts[suffix]+=1
    return counts


def _scan_theme_folder_for_export(folder):
    folder=Path(folder).expanduser()
    result={'theme_folder':str(folder),'included_files':[],'counts':{'.svg':0,'.png':0,'.qss':0},'detected_theme_configuration':'','detected_splash':''}
    if not folder.is_dir():return result
    files=[]
    for path in sorted(folder.rglob('*')):
        if not path.is_file():continue
        rel=path.relative_to(folder).as_posix()
        if any(rel.startswith(n+'/') or '/'+n+'/' in rel for n in (RUNTIME_DIR_NAME,'.UI_Launcher_runtime')):continue
        if path.suffix.lower() not in EXPORTABLE_THEME_EXTENSIONS:continue
        if path.suffix.lower()=='.py' and not rel.startswith('scripts/'):continue
        if rel.lower()!=CUSTOM_LICENSE_BRIEF_RELPATH.lower() and _is_safe_relpath(rel):files.append(rel)
    top=[rel for rel in files if '/' not in rel]
    configs=[rel for rel in top if Path(rel).name.lower()==CONFIG_NAME.lower()]
    result['included_files']=files
    result['counts']=_count_suffixes(files)
    result['detected_theme_configuration']=configs[0] if len(configs)==1 else ''
    result['detected_splash']=_detect_splash_relpath(files)
    return result


def _effective_export_file_list(scan,folder,license_choice,theme_package):
    files=[rel for rel in list(scan.get('included_files',[])) if Path(rel).name.lower()!=SKIPPED_NAME.lower() and rel.lower()!=CUSTOM_LICENSE_BRIEF_RELPATH.lower()]
    if _is_artwork_only_theme_package(theme_package):
        files=[rel for rel in files if Path(rel).suffix.lower() not in {'.cfg','.qss'} and Path(rel).name.lower()!=CONFIG_NAME.lower()]
    if license_choice==CUSTOM_LICENSE_OPTION:
        if (Path(folder)/THEME_LICENSE_RELPATH).is_file() and THEME_LICENSE_RELPATH not in files:files.append(THEME_LICENSE_RELPATH)
    elif license_choice and THEME_LICENSE_RELPATH not in files:
        files.append(THEME_LICENSE_RELPATH)
    if license_choice and CUSTOM_LICENSE_BRIEF_RELPATH not in files:
        files.append(CUSTOM_LICENSE_BRIEF_RELPATH)
    return sorted(set(files),key=str.lower)


def _normalize_external_asset_url(url):
    raw=str(url or '').strip()
    if not raw:return raw
    parsed=urllib_parse.urlparse(raw);host=(parsed.netloc or '').lower();parts=[x for x in (parsed.path or '').split('/') if x]
    if host=='github.com' and len(parts)>=5 and parts[2]=='blob':
        owner,repo,_blob,branch=parts[:4]; remainder='/'.join(parts[4:])
        return urllib_parse.urlunparse(('https','raw.githubusercontent.com',f'/{owner}/{repo}/{branch}/{remainder}','','',''))
    if host in {'www.dropbox.com','dropbox.com'}:
        q=urllib_parse.parse_qs(parsed.query,keep_blank_values=True);q['dl']=['1']
        return urllib_parse.urlunparse(parsed._replace(query=urllib_parse.urlencode(q,doseq=True)))
    return raw


def _external_asset_filename_from_url(url,expected_suffix):
    normalized=_normalize_external_asset_url(url);parsed=urllib_parse.urlparse(normalized)
    filename=Path(urllib_parse.unquote(parsed.path or '')).name.strip()
    if not filename:raise LauncherError('Could not determine a file name from URL:\n'+str(url))
    if Path(filename).suffix.lower()!=expected_suffix.lower():raise LauncherError('The URL must point to a '+expected_suffix+' file:\n'+str(url))
    return filename


def _prepare_license_for_export(values,theme_folder):
    choice=values.get('license','').strip();target=Path(theme_folder)/THEME_LICENSE_RELPATH
    target.parent.mkdir(parents=True,exist_ok=True)
    if choice==CUSTOM_LICENSE_OPTION:
        if not target.is_file():raise LauncherError(f'Custom License requires "{THEME_LICENSE_RELPATH}" inside the Theme Folder.')
        return THEME_LICENSE_RELPATH
    source=_license_source_path(choice)
    if source is None or not source.is_file():raise LauncherError(f'Selected CC license file was not found in "{CC_LICENSES_DIR_NAME}".')
    shutil.copy2(source,target)
    return THEME_LICENSE_RELPATH


def _create_theme_package(values,scan,output_path):
    # Package creation is delegated to the exact bundled bundled launcher engine 1.52.15
    # implementation. The PySide dialog is only a native front-end.
    req={'values':dict(values),'output_path':str(Path(output_path).expanduser().resolve())}
    fd,name=tempfile.mkstemp(prefix='external-theme-creator-export-',suffix='.json');os.close(fd)
    try:
        Path(name).write_text(json.dumps(req,indent=2,ensure_ascii=False),encoding='utf-8')
        out=_runtime_call(['--export-request',name],require_crypto=True,timeout=180)
        result=json.loads(out)
        return result['manifest'],Path(result['output_path'])
    finally:
        try:Path(name).unlink(missing_ok=True)
        except Exception:pass


def _export_category_summary(files):
    paths=[str(rel).replace('\\','/').lower() for rel in files]
    def count(predicate):
        return sum(1 for rel in paths if predicate(rel))
    summary=[
        ('Icons',count(lambda r:r.startswith('icons/'))),
        ('Configuration instructions (.json)',count(lambda r:r=='theme-configuration.json')),
        ('Stylesheet (.qss)',count(lambda r:r.endswith('.qss'))),
        ('Scripts',count(lambda r:r.startswith('scripts/') and r.endswith('.py'))),
        ('Splash graphics',count(lambda r:r.startswith('splash/') and r.endswith('.png'))),
        ('Shortcut icons',count(lambda r:r.startswith('shortcut-icon/') and r.endswith(('.png','.ico','.icns','.svg')))),
        ('License files',count(lambda r:r.startswith('license/') and r.endswith('.lic'))),
    ]
    return '\n'.join(f'{label}: {number}' for label,number in summary)


class ExportDialog(QtWidgets.QDialog):
    PFX='Export/'
    def __init__(self):
        super().__init__(mw());self.setWindowTitle('Export theme');self.resize(900,850);self.setMinimumSize(760,560)
        root=QtWidgets.QVBoxLayout(self)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);root.addWidget(scroll,1)
        body=QtWidgets.QWidget();scroll.setWidget(body);v=QtWidgets.QVBoxLayout(body)
        self.folder=PathRow('Theme Folder',True);self.folder.edit.setText(params().GetString(FOLDER_KEY,''));self.folder.edit.textChanged.connect(self.refresh);v.addWidget(self.folder)
        meta=QtWidgets.QGroupBox('Theme Metadata');mg=QtWidgets.QGridLayout(meta);v.addWidget(meta)
        self.fields={};row=0
        def line(label,key,readonly=False):
            nonlocal row;mg.addWidget(QtWidgets.QLabel(label),row,0);w=QtWidgets.QLineEdit();w.setReadOnly(readonly);mg.addWidget(w,row,1,1,3);self.fields[key]=w;row+=1;return w
        line('Theme Name','theme_name');line('Theme ID','theme_id',True);line('Theme Version','theme_version');line('Author Name','author_name');line('FreeCAD Version Tested','freecad_version_tested')
        mg.addWidget(QtWidgets.QLabel('Author Key'),row,0);self.fields['author_key_file']=QtWidgets.QLineEdit();mg.addWidget(self.fields['author_key_file'],row,1);bb=QtWidgets.QPushButton('Browse');bb.clicked.connect(self.browse_key);mg.addWidget(bb,row,2);cb=QtWidgets.QPushButton('Create Author Key');cb.clicked.connect(self.create_key);mg.addWidget(cb,row,3);row+=1
        def text(label,key,height=70):
            nonlocal row;mg.addWidget(QtWidgets.QLabel(label),row,0,QtCore.Qt.AlignTop);w=QtWidgets.QPlainTextEdit();w.setFixedHeight(height);mg.addWidget(w,row,1,1,3);self.fields[key]=w;row+=1;return w
        text('Description','description',75);text('Copyright','copyright',55)
        mg.addWidget(QtWidgets.QLabel('License'),row,0);self.license_combo=QtWidgets.QComboBox();self.license_combo.addItems(_license_options());mg.addWidget(self.license_combo,row,1,1,3);row+=1
        text('License Brief','license_terms',75)
        auto=QtWidgets.QGroupBox('Auto-generated Package Info');ag=QtWidgets.QFormLayout(auto);v.addWidget(auto)
        self.auto={}
        for label,key,val in [('Schema Version','schema',THEME_SCHEMA_VERSION),('Package Type','type',THEME_PACKAGE_TYPE),('External Theme Creator Compatibility','launcher',UI_LAUNCHER_COMPAT_VERSION),('External Theme Creator Version','creator',EXTERNAL_THEME_CREATOR_VERSION),('Payload Encryption','encryption',THEME_PAYLOAD_ENCRYPTION),('Key Fingerprint','fingerprint','')]:
            w=QtWidgets.QLineEdit(val);w.setReadOnly(True);ag.addRow(label,w);self.auto[key]=w
        summary=QtWidgets.QGroupBox('Theme Folder Summary');sg=QtWidgets.QGridLayout(summary);v.addWidget(summary,1)
        self.summary={};rr=0
        for label,key in [('Theme Folder','folder'),('SVG count','svg'),('PNG count','png'),('QSS count','qss'),('Total included files','total')]:
            sg.addWidget(QtWidgets.QLabel(label),rr,0);w=QtWidgets.QLineEdit();w.setReadOnly(True);sg.addWidget(w,rr,1);self.summary[key]=w;rr+=1
        sg.addWidget(QtWidgets.QLabel('Included files'),rr,0,QtCore.Qt.AlignTop)
        files_column=QtWidgets.QVBoxLayout()
        self.file_counts=QtWidgets.QLabel()
        self.file_counts.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        files_column.addWidget(self.file_counts)
        self.included=QtWidgets.QPlainTextEdit()
        self.included.setReadOnly(True)
        self.included.setMinimumHeight(150)
        files_column.addWidget(self.included)
        sg.addLayout(files_column,rr,1)
        rr+=1
        sg.addWidget(QtWidgets.QLabel('Validation'),rr,0,QtCore.Qt.AlignTop);self.validation=QtWidgets.QPlainTextEdit();self.validation.setReadOnly(True);self.validation.setMinimumHeight(100);sg.addWidget(self.validation,rr,1)
        buttons=QtWidgets.QHBoxLayout();buttons.addStretch();cancel=QtWidgets.QPushButton('Cancel');cancel.clicked.connect(self.reject);validate=QtWidgets.QPushButton('Validate');validate.clicked.connect(self.refresh);export=QtWidgets.QPushButton('Export');export.clicked.connect(self.export);buttons.addWidget(cancel);buttons.addWidget(validate);buttons.addWidget(export);root.addLayout(buttons)
        self._load_settings()
        self.license_combo.currentTextChanged.connect(self.license_changed)
        for key,w in self.fields.items():
            if hasattr(w,'textChanged'):w.textChanged.connect(self.refresh)
        self.refresh()

    def _get(self,key):
        w=self.fields[key]
        return w.toPlainText().strip() if isinstance(w,QtWidgets.QPlainTextEdit) else w.text().strip()
    def _set(self,key,value):
        w=self.fields[key]
        if isinstance(w,QtWidgets.QPlainTextEdit):w.setPlainText(str(value or ''))
        else:w.setText(str(value or ''))
    def _param(self,key,default=''):return params().GetString(self.PFX+key,default)
    def _load_settings(self):
        self._set('theme_name',self._param('theme_name',''));self._set('theme_version',self._param('theme_version','1.0.0'));self._set('author_name',self._param('author_name',''))
        try:fc='.'.join(str(x) for x in App.Version()[:3])
        except Exception:fc=''
        self._set('freecad_version_tested',self._param('freecad_version_tested',fc));self._set('author_key_file',self._param('author_key_file',''))
        for key,default in [('description',''),('copyright',''),('license_terms','')]:self._set(key,self._param(key,default))
        lic=self._param('license','');lic='LGPL' if lic=='FreeCAD (LGPL-2.1-or-later)' else lic;i=self.license_combo.findText(lic);self.license_combo.setCurrentIndex(i if i>=0 else 0)
        if self.license_combo.currentText()==CUSTOM_LICENSE_OPTION:
            self._set('license_terms',self._custom_license_brief() or self._get('license_terms'))
        elif not self._get('license_terms'):
            self._set('license_terms',_default_license_brief(self.license_combo.currentText()))
    def _custom_license_brief(self):
        path=Path(self.folder.edit.text().strip()).expanduser()/CUSTOM_LICENSE_BRIEF_RELPATH
        return _read_text(path).strip() if path.is_file() else ''
    def _save_settings(self,values):
        params().SetString(FOLDER_KEY,values['theme_folder'])
        for key in ('theme_name','theme_version','author_name','freecad_version_tested','author_key_file','description','copyright','license_terms','license'):params().SetString(self.PFX+key,str(values.get(key,'')))
    def browse_key(self):
        p=QtWidgets.QFileDialog.getOpenFileName(self,'Select Author Key',self._get('author_key_file'),'PEM files (*.pem);;All files (*)')[0]
        if p:self._set('author_key_file',p)
    def create_key(self):
        author=self._get('author_name')
        if not author:return error('Author Name is required before creating an Author Key.')
        path=QtWidgets.QFileDialog.getSaveFileName(self,'Create Author Key',_slugify_theme_id(author)+'_private.pem','PEM files (*.pem);;All files (*)')[0]
        if not path:return
        if not path.lower().endswith('.pem'):path+='.pem'
        try:
            Fernet,serialization,Ed25519PrivateKey,Ed25519PublicKey=_require_crypto();key=Ed25519PrivateKey.generate()
            private=key.private_bytes(encoding=serialization.Encoding.PEM,format=serialization.PrivateFormat.PKCS8,encryption_algorithm=serialization.NoEncryption())
            public=key.public_key().public_bytes(encoding=serialization.Encoding.PEM,format=serialization.PublicFormat.SubjectPublicKeyInfo)
            pp=Path(path);pub=pp.with_name(pp.stem+'.public.pem');pp.write_bytes(private);pub.write_bytes(public);self._set('author_key_file',str(pp));self.refresh();info('Author Key created:\n'+str(pp)+'\n\nPublic Key created:\n'+str(pub))
        except Exception as exc:error(str(exc))
    def license_changed(self,choice):
        self._set('license_terms',self._custom_license_brief() if choice==CUSTOM_LICENSE_OPTION else _default_license_brief(choice))
        self.refresh()
    def values(self):
        d={key:self._get(key) for key in self.fields};d['theme_folder']=self.folder.edit.text().strip();d['theme_package']=THEME_PACKAGE_OPTION_COMPLETE;d['license']=self.license_combo.currentText().strip();d['require_external_cfg']=False;d['external_cfg_url']='';d['require_external_qss']=False;d['external_qss_url']='';d['theme_id']=_slugify_theme_id(d['theme_name']);return d
    def validate_values(self,values,scan):
        e=[];folder=Path(values['theme_folder']).expanduser()
        if not folder.is_dir():e.append('Theme Folder does not exist or is not a folder.')
        for key,label in [('theme_name','Theme Name'),('theme_version','Theme Version'),('author_name','Author Name'),('freecad_version_tested','FreeCAD Version Tested'),('description','Description'),('copyright','Copyright'),('license','License'),('license_terms','License Brief')]:
            if not values.get(key):e.append(label+' is required.')
        if not values['theme_id']:e.append('Theme ID could not be generated from Theme Name.')
        if values.get('license')==CUSTOM_LICENSE_OPTION:
            if not (folder/THEME_LICENSE_RELPATH).is_file():e.append(f'Custom License requires "{THEME_LICENSE_RELPATH}" inside the Theme Folder.')
        elif values.get('license') and _license_source_path(values['license']) is None:e.append(f'Selected license file was not found in "{CC_LICENSES_DIR_NAME}".')
        keyfile=Path(values.get('author_key_file','')).expanduser()
        if not values.get('author_key_file'):e.append('Author Key is required.')
        elif not keyfile.is_file():e.append('Author Key does not exist or is not a file.')
        else:
            try:self.auto['fingerprint'].setText(_load_author_private_key(keyfile)[2])
            except Exception as exc:e.append(str(exc))
        effective=_effective_export_file_list(scan,folder,values.get('license',''),values['theme_package'])
        counts=scan.get('counts',{})
        if not effective:e.append('No exportable theme files were found in the Theme Folder.')
        if counts.get('.svg',0)+counts.get('.png',0)==0:e.append('The Theme Folder must contain at least one .svg or .png asset.')
        if not scan.get('detected_theme_configuration'):e.append(f'A Complete Theme requires a top-level "{CONFIG_NAME}" file.')
        return e
    def refresh(self,*_args):
        try:
            values=self.values();self._set('theme_id',values['theme_id']);scan=_scan_theme_folder_for_export(values['theme_folder']);counts=scan.get('counts',{});effective=_effective_export_file_list(scan,Path(values['theme_folder']).expanduser(),values.get('license',''),values['theme_package'])
            self.summary['folder'].setText(values['theme_folder']);self.summary['svg'].setText(str(counts.get('.svg',0)));self.summary['png'].setText(str(counts.get('.png',0)));self.summary['qss'].setText(str(counts.get('.qss',0)));self.summary['total'].setText(str(len(effective)));self.included.setPlainText('\n'.join(effective));self.file_counts.setText(_export_category_summary(effective));errs=self.validate_values(values,scan);self.validation.setPlainText('\n'.join('• '+x for x in errs) if errs else 'Ready to export.')
        except Exception as exc:self.validation.setPlainText('• '+str(exc))
    def export(self):
        values=self.values();scan=_scan_theme_folder_for_export(values['theme_folder']);errs=self.validate_values(values,scan)
        if errs:self.refresh();return error('\n'.join(errs))
        default=f"{values['theme_id']}_v{values['theme_version']}{THEME_PACKAGE_EXTENSION}"
        path=QtWidgets.QFileDialog.getSaveFileName(self,'Export Theme',default,'Theme files (*.fctheme);;All files (*)')[0]
        if not path:return
        if not path.lower().endswith(THEME_PACKAGE_EXTENSION):path+=THEME_PACKAGE_EXTENSION
        try:
            manifest,out=_create_theme_package(values,scan,Path(path));self._save_settings(values);info('Theme exported successfully.\n\nTheme Name: {}\nTheme ID: {}\nTheme Version: {}\nIncluded Files: {}\n\nOutput:\n{}'.format(manifest['theme_name'],manifest['theme_id'],manifest['theme_version'],manifest['payload_file_count'],out));self.accept()
        except Exception as exc:error(str(exc))

def show_apply_theme(): ApplyDialog().exec()
def show_develop_theme(): DevelopDialog().exec()
def show_cfg_instructions():
    global _cfg_dialog
    if _cfg_dialog is None:
        _cfg_dialog=CFGDialog()
        try:_cfg_dialog.setWindowModality(QtCore.Qt.NonModal)
        except Exception:pass
    _cfg_dialog.show()
    try:
        _cfg_dialog.raise_()
        _cfg_dialog.activateWindow()
    except Exception:
        pass

def show_export_theme(): ExportDialog().exec()

class SimpleCommand:
    def __init__(self,label,tip,icon,fn): self.label,self.tip,self.icon,self.fn=label,tip,icon,fn
    def GetResources(self): return {'MenuText':self.label,'ToolTip':self.tip,'Pixmap':self.icon}
    def Activated(self): self.fn()
    def IsActive(self): return True


def show_ui_inspector():
    import ExternalThemeCreatorInspector
    ExternalThemeCreatorInspector.show_ui_inspector()
