"""Private, verified binary dependency bootstrap for External Theme Creator.

Windows downloads use PowerShell's HTTPS stack because FreeCAD 26.3 may have
an incompatible Python ssl.py/_ssl.pyd pair. No changes to FreeCAD's files.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PACKAGES = ('cryptography', 'cffi', 'pycparser')
DIAGNOSTIC = ('from cryptography.fernet import Fernet; '
              'from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; '
              'k=Ed25519PrivateKey.generate(); m=b"External Theme Creator test"; '
              'k.public_key().verify(k.sign(m),m); '
              'f=Fernet(Fernet.generate_key()); assert f.decrypt(f.encrypt(m)) == m; '
              'print("cryptography signing and encryption: PASS")')


def _root():
    if os.name == 'nt':
        return Path(os.environ.get('APPDATA') or (Path.home()/'AppData'/'Roaming'))/'ExternalThemeCreator'/'python-deps'
    return Path.home()/'.local'/'share'/'ExternalThemeCreator'/'python-deps'


def _folder(version):
    return _root()/('py%d%d' % (version[0],version[1]))


def activate(version=None):
    version = version or sys.version_info[:2]
    target = str(_folder(version))
    if target not in sys.path:
        sys.path.insert(0,target)
    return target


def _confirm(parent):
    try:
        from PySide import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets
    msg = ('Signed theme export and Author Keys require cryptography.\n\n'
           'External Theme Creator can automatically download verified binary packages '
           'from PyPI using Windows HTTPS, install them into your user profile, '
           'and test signing and encryption. FreeCAD files will not be modified.\n\n'
           'Continue?')
    return QtWidgets.QMessageBox.question(parent,'External Theme Creator dependency',msg,
        QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No,
        QtWidgets.QMessageBox.Yes)==QtWidgets.QMessageBox.Yes


def _run(cmd, *, timeout=240, env=None):
    result=subprocess.run([str(s) for s in cmd], text=True, capture_output=True,
                          timeout=timeout, env=env,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'process failed')[-1800:])
    return result.stdout


def _powershell(script, *args):
    if os.name != 'nt':
        raise RuntimeError('Windows PowerShell downloader is only available on Windows.')
    with tempfile.TemporaryDirectory(prefix='tc_ps_') as d:
        ps = Path(d)/'download.ps1'
        ps.write_text(script,encoding='utf-8-sig')
        exe = os.path.join(os.environ.get('SystemRoot',r'C:\Windows'),
                           'System32','WindowsPowerShell','v1.0','powershell.exe')
        return _run([exe,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                     '-File',ps,*args],timeout=180)


_PS_DOWNLOAD = r'''
param([string]$Url,[string]$Destination)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -MaximumRedirection 5
'''


def _download(url, path):
    if not url.startswith('https://files.pythonhosted.org/') and not url.startswith('https://pypi.org/'):
        raise RuntimeError('Unexpected wheel download host: '+url)
    _powershell(_PS_DOWNLOAD,url,str(path))


def _wheel_tags(exe):
    # Ask the target interpreter, never assume the host interpreter's ABI.
    code=('from pip._vendor.packaging.tags import sys_tags; '
          'print(*map(str,sys_tags()), sep=chr(10))')
    output=_run([exe,'-c',code],timeout=25)
    return [s.strip() for s in output.splitlines() if s.strip()]


def _select_wheel(meta, tags):
    ranks={tag:i for i,tag in enumerate(tags)}
    eligible=[]
    for entry in meta.get('urls',[]):
        if entry.get('packagetype')!='bdist_wheel' or entry.get('yanked'):continue
        filename=entry.get('filename','')
        stem=filename[:-4] if filename.endswith('.whl') else ''
        pieces=stem.rsplit('-',3)
        if len(pieces)!=4:continue
        py,abi,platform_tag=pieces[1:]
        rank=min((ranks[t] for p in py.split('.') for a in abi.split('.')
                  for plat in platform_tag.split('.')
                  if (t:=p+'-'+a+'-'+plat) in ranks),default=None)
        if rank is not None:eligible.append((rank,entry))
    if not eligible:
        raise RuntimeError('No matching precompiled Windows wheel on PyPI for '+
                           str(meta.get('info',{}).get('name','package')))
    return min(eligible,key=lambda x:x[0])[1]


def _fetch_wheels(exe, wheel_dir):
    tags=_wheel_tags(exe)
    for package in PACKAGES:
        info_path=wheel_dir/(package+'.json')
        _download('https://pypi.org/pypi/'+package+'/json',info_path)
        meta=json.loads(info_path.read_text(encoding='utf-8'))
        entry=_select_wheel(meta,tags)
        filename=entry['filename']
        target=wheel_dir/filename
        _download(entry['url'],target)
        expected=entry.get('digests',{}).get('sha256')
        actual=hashlib.sha256(target.read_bytes()).hexdigest()
        if not expected or actual.lower()!=expected.lower():
            raise RuntimeError('SHA-256 verification failed for '+filename)
    return wheel_dir


def _diagnose(exe,version):
    target=_folder(version)
    env=os.environ.copy()
    env['PYTHONPATH']=str(target)+os.pathsep+env.get('PYTHONPATH','')
    try:
        return _run([exe,'-c',DIAGNOSTIC],timeout=25,env=env)
    except Exception as exc:
        raise RuntimeError('Dependency diagnostic failed (import, Ed25519 or Fernet): '+str(exc)) from exc


def _install(exe,version):
    target=_folder(version)
    target.mkdir(parents=True,exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='tc_wheels_') as temp:
            directory=Path(temp)
            try:
                _fetch_wheels(exe,directory)
            except Exception as exc:
                raise RuntimeError('Download or wheel verification failed: '+str(exc)) from exc
            try:
                _run([exe,'-m','pip','install','--no-index','--find-links',directory,
                      '--disable-pip-version-check','--only-binary=:all:',
                      '--upgrade','--target',target,'cryptography'],timeout=180)
            except Exception as exc:
                raise RuntimeError('Local wheel installation failed: '+str(exc)) from exc
        _diagnose(exe,version)
    except Exception as exc:
        raise RuntimeError('cryptography setup failed.\n\n'+str(exc)) from exc
    importlib.invalidate_caches()
    activate(version)
    return True


def _interpreter_version(exe):
    out=_run([exe,'-c','import sys;print("%s.%s" % sys.version_info[:2])'],timeout=15)
    return tuple(int(part) for part in out.strip().splitlines()[-1].split('.'))


def _ensure(exe,parent=None):
    version=_interpreter_version(exe)
    try:
        _diagnose(exe,version)
    except Exception:
        if not _confirm(parent):return None
        _install(exe,version)
    return str(_folder(version))


def ensure_current(parent=None):
    activate()
    try:
        exec(DIAGNOSTIC, {})
        return True
    except (ImportError,OSError,AssertionError):
        pass
    exe=Path(sys.executable)
    if 'freecad' in exe.name.lower():exe=exe.parent/'python.exe'
    if not exe.is_file():
        raise RuntimeError('FreeCAD Python interpreter not found: '+str(exe))
    if _ensure(exe,parent) is None:return False
    importlib.invalidate_caches()
    activate()
    # Confirm inside FreeCAD as well, not merely in a subprocess.
    try:
        exec(DIAGNOSTIC,{})
    except Exception as exc:
        raise RuntimeError('Installed successfully but FreeCAD import diagnostic failed: '+str(exc)) from exc
    return True


def prepare_interpreter(exe,parent=None):
    return _ensure(Path(exe),parent)

activate()
