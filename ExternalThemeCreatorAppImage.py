"""Persistent AppImage launcher bootstrap. No FreeCAD import at module load."""
import os
import platform
from pathlib import Path

def make_bootstrap(mode, runtime_file):
    """Start ETC within a newly mounted AppImage, never via an old mount."""
    image = os.environ.get('APPIMAGE', '').strip()
    if platform.system().lower() != 'linux' or not image or not Path(image).is_file():
        return None
    from ExternalThemeCreatorMigration import application_dir
    directory = application_dir() / 'AppImageBootstrap'
    directory.mkdir(parents=True, exist_ok=True)
    macro = directory / ('launch_' + mode + '.FCMacro')
    runtime_file = Path(runtime_file).resolve()
    # The first FreeCAD process is a bootstrap. It starts the themed session,
    # then closes itself; the runtime resolves the fresh APPIMAGE mount.
    code = (
        'import os,sys,traceback\n'
        'from pathlib import Path\n'
        'import FreeCADGui as Gui\n'
        'from PySide6 import QtCore\n'
        '# Hide the bootstrap instance as early as the startup macro permits.\n'
        'QtCore.QTimer.singleShot(0, lambda: Gui.getMainWindow().hide() if Gui.getMainWindow() else None)\n'
        f'_ETC_FILE = {str(runtime_file)!r}\n'
        f'_ETC_MODE = {mode!r}\n'
        'def _etc_start():\n'
        '    try:\n'
        '        root = str(Path(_ETC_FILE).parent)\n'
        '        if root not in sys.path: sys.path.insert(0, root)\n'
        '        import ExternalThemeCreatorRuntime as ETC\n'
        '        code = ETC._launch(_ETC_MODE)\n'
        '        if code: raise RuntimeError("ETC themed launch returned failure")\n'
        '        QtCore.QTimer.singleShot(1000, lambda: Gui.getMainWindow().close())\n'
        '    except Exception:\n'
        f'        with open({str(directory / "bootstrap-error.log")!r}, "a", encoding="utf-8") as f:\n'
        '            f.write(traceback.format_exc() + "\\n")\n'
        'QtCore.QTimer.singleShot(750, _etc_start)\n'
    )
    macro.write_text(code, encoding='utf-8')
    return [str(Path(image).resolve()), str(macro)]
