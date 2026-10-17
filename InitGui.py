"""FreeCAD entry point for the External Theme Creator workbench.

FreeCAD may execute InitGui.py in a disposable namespace. Keep all persistent
command and workbench implementations in a regular imported Python module,
whose globals remain valid after this entry point finishes.
"""

import ExternalThemeCreatorBootstrap  # noqa: F401 - registers commands and workbench
