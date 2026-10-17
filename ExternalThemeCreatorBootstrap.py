"""External Theme Creator persistent GUI bootstrap.

Keep startup lightweight, but register External Theme Creator command stubs immediately.
FreeCAD can then resolve these commands while it rebuilds custom toolbars from
other workbenches, preserving the user's saved action order.  The functional
ExternalThemeCreatorCommands module remains lazy and is imported only when a command
is activated.
"""

import importlib.util
import os

import FreeCAD as App
import FreeCADGui as Gui


def _addon_dir():
    """Locate the workbench without relying on __file__ in FreeCAD InitGui."""
    spec = importlib.util.find_spec("ExternalThemeCreatorCommands")
    if spec is not None and spec.origin:
        return os.path.dirname(os.path.abspath(spec.origin))
    return ""


_ADDON_DIR = _addon_dir()
_ICON_DIR = os.path.join(_ADDON_DIR, "Resources", "icons") if _ADDON_DIR else ""
if os.path.isdir(_ICON_DIR):
    Gui.addIconPath(_ICON_DIR)


class LazyCommand:
    """Lightweight command proxy; imports implementation only on activation."""

    def __init__(self, label, tooltip, icon_name, function_name):
        self.label = label
        self.tooltip = tooltip
        self.icon_name = icon_name
        self.function_name = function_name

    def GetResources(self):
        icon = os.path.join(_ICON_DIR, self.icon_name)
        return {
            "Pixmap": icon if os.path.isfile(icon) else "",
            "MenuText": self.label,
            "ToolTip": self.tooltip,
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        return True

    def Activated(self):
        try:
            import ExternalThemeCreatorCommands as TC
            getattr(TC, self.function_name)()
        except Exception:
            import traceback
            App.Console.PrintError(
                "External Theme Creator: command '%s' failed.\n%s\n"
                % (self.label, traceback.format_exc())
            )


# Register these stubs as soon as InitGui.py is loaded.  This intentionally
# happens before ExternalThemeCreatorWorkbench.Initialize(): custom toolbars belonging
# to other workbenches may reference External Theme Creator commands during FreeCAD's
# startup/workbench reconstruction, before the External Theme Creator workbench itself
# has ever been activated.
_COMMANDS = {
    "ExternalThemeCreator_Apply": LazyCommand(
        "Apply theme", "Open and apply an exported .fctheme package",
        "ETC_apply.svg", "show_apply_theme"
    ),
    "ExternalThemeCreator_Develop": LazyCommand(
        "Develop theme", "Work directly from a Theme Folder",
        "ETC_develop.svg", "show_develop_theme"
    ),
    "ExternalThemeCreator_ReloadQSS": LazyCommand(
        "QSS reload", "Reload the active development QSS",
        "ETC_reload_QSS.svg", "reload_qss"
    ),
    "ExternalThemeCreator_ReloadIcons": LazyCommand(
        "Icons reload", "Reload the active launch-time theme icons",
        "ETC_reload_icons.svg", "reload_icons"
    ),
    "ExternalThemeCreator_CFG": LazyCommand(
        "CFG Instructions", "Generate or capture theme configuration instructions",
        "ETC_cfg.svg", "show_cfg_instructions"
    ),
    "ExternalThemeCreator_Inspector": LazyCommand(
        "UI Inspector", "Inspect FreeCAD widgets under the mouse (Ctrl+Shift+I)",
        "ETC_inspector.svg", "show_ui_inspector"
    ),
    "ExternalThemeCreator_Export": LazyCommand(
        "Export theme", "Export the current Theme Folder",
        "ETC_export.svg", "show_export_theme"
    ),
}

for _name, _command in _COMMANDS.items():
    Gui.addCommand(_name, _command)


class ExternalThemeCreatorWorkbench(Gui.Workbench):
    Icon = os.path.join(_ICON_DIR, "ETC_export.svg")
    MenuText = "External Theme Creator"
    ToolTip = "Create, develop, apply, reload, and export FreeCAD UI themes"

    _initialized = False

    def Initialize(self):
        if self._initialized:
            return

        command_names = list(_COMMANDS.keys())
        self.appendToolbar("External Theme Creator", command_names)
        self.appendMenu("External Theme Creator", command_names)
        self._initialized = True
        App.Console.PrintMessage("External Theme Creator: workbench initialized.\n")

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(ExternalThemeCreatorWorkbench())
