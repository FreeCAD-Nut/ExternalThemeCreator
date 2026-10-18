#!/usr/bin/env python3
"""Separate native-resolution splash process for External Theme Creator-managed launches.

Uses bundled FreeCAD Python/PySide6. The original image is never modified.
"""
import sys
import time
import os
from pathlib import Path

def _configure_windows_dpi():
    """Match FreeCAD's per-monitor DPI awareness before QApplication exists."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10+).
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        import ctypes
        shcore = ctypes.WinDLL('shcore', use_last_error=True)
        # PROCESS_PER_MONITOR_DPI_AWARE. May return ACCESS_DENIED if already set.
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def _monitor_dpr(screen):
    """Use Qt's physical DPI ratio, independently verify Windows monitor DPI."""
    dpr = float(screen.devicePixelRatio()) if screen else 1.0
    if os.name != 'nt':
        return max(dpr, 1.0)
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        shcore = ctypes.WinDLL('shcore', use_last_error=True)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        monitor = user32.MonitorFromPoint(pt, 2)
        if monitor:
            xdpi = wintypes.UINT()
            ydpi = wintypes.UINT()
            # MDT_EFFECTIVE_DPI = 0; dpi 96 corresponds to 100%.
            shcore.GetDpiForMonitor.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
            shcore.GetDpiForMonitor.restype = ctypes.c_long
            if shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(xdpi), ctypes.byref(ydpi)) == 0 and xdpi.value:
                return float(xdpi.value) / 96.0
    except Exception:
        pass
    return max(dpr, 1.0)


def _macos_hide_splash_dock_icon():
    """A splash is an accessory window, not a second Dock application.

    Use the macOS Cocoa runtime directly because FreeCAD's bundled Python does
    not necessarily ship PyObjC. This is a best-effort appearance change; the
    splash must continue to work if the runtime call is unavailable.
    """
    if sys.platform != 'darwin':
        return
    try:
        import ctypes
        from ctypes.util import find_library
        objc = ctypes.CDLL(find_library('objc') or '/usr/lib/libobjc.A.dylib')
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        objc.objc_msgSend.restype = ctypes.c_void_p
        nsapp = objc.objc_msgSend(objc.objc_getClass(b'NSApplication'),
                                 objc.sel_registerName(b'sharedApplication'))
        if not nsapp:
            return
        # NSApplicationActivationPolicyAccessory = 1. No Dock icon, but
        # accessory windows (including QSplashScreen) remain permitted.
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        objc.objc_msgSend.restype = ctypes.c_bool
        success = objc.objc_msgSend(nsapp,
                                    objc.sel_registerName(b'setActivationPolicy:'), 1)
        print('macOS splash accessory policy applied:', bool(success), flush=True)
    except Exception as exc:
        print('macOS splash accessory policy unavailable:', repr(exc), flush=True)


def main():
    if len(sys.argv) != 3:
        return 2
    source, stop = Path(sys.argv[1]), Path(sys.argv[2])
    _configure_windows_dpi()
    print('Splash helper Python:', sys.executable, flush=True)
    print('Splash helper source:', source, 'exists:', source.is_file(), flush=True)
    print('Splash helper Qt plugin path:', os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH', '<unset>'), flush=True)
    from PySide6 import QtCore, QtGui, QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
    _macos_hide_splash_dock_icon()
    pixmap = QtGui.QPixmap(str(source))
    if pixmap.isNull():
        return 3
    screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or QtGui.QGuiApplication.primaryScreen()
    dpr = _monitor_dpr(screen)
    print('Splash helper DPI: windows=%.3f qt=%.3f' % (dpr, float(screen.devicePixelRatio()) if screen else 1.0), flush=True)
    pixmap.setDevicePixelRatio(dpr if dpr > 0 else 1.0)
    splash = QtWidgets.QSplashScreen(pixmap, QtCore.Qt.WindowStaysOnTopHint)
    splash.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
    logical = pixmap.deviceIndependentSize()
    splash.setFixedSize(max(1, round(logical.width())), max(1, round(logical.height())))
    splash.clearMask()
    if screen:
        rect = screen.availableGeometry()
        splash.move(rect.center().x()-splash.width()//2, rect.center().y()-splash.height()//2)
    splash.show()
    splash.clearMask()
    app.processEvents()
    Path(str(stop)+'.ready').write_text('ready', encoding='ascii')
    print('Splash helper ready pid=%s stop=%s' % (os.getpid(), stop), flush=True)
    started = time.monotonic()
    timer = QtCore.QTimer()
    def check():
        if stop.exists() or time.monotonic() - started > 110:
            print('Splash helper closing: ' + ('stop signal' if stop.exists() else 'safety timeout'), flush=True)
            timer.stop()
            splash.close()
            app.quit()
    timer.timeout.connect(check)
    timer.start(150)
    return app.exec()

if __name__ == '__main__':
    raise SystemExit(main())
