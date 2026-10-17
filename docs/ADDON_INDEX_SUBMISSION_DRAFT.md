# Addon Index submission draft (do not submit until release checks pass)

**Repository:** [INSERT VERIFIED PUBLIC GITHUB REPOSITORY URL]

**Addon:** External Theme Creator

**Description:** A FreeCAD workbench for developing, applying and exporting external UI themes, including QSS/stylesheets, icon overrides, theme configuration instructions, optional scripts and splash assets. Includes a UI Inspector, live QSS/Icon reload and optional theme export signing/encryption capabilities.

**License:** LGPL-2.1-or-later for code; verify all bundled asset licenses before submission.

**Installation:** Workbench in repository root (`InitGui.py`, `Init.py`, `package.xml`).

**Tested versions:** [INSERT VERIFIED STABLE/DEVELOPMENT VERSIONS, OS AND Qt]

**Dependencies:** Core FreeCAD/PySide. Optional cryptography signing/encryption feature uses cryptography/cffi/pycparser and has a user-confirmed install path. Describe its security model and comply with Addon Index package policy.

**Evidence:** [LINK SCREENSHOTS], [LINK PUBLIC USER TEST/FEEDBACK], [LINK ISSUE TRACKER]

**Maintenance commitment:** [MAINTAINER TO CONFIRM]

**Potential reviewer questions:** Side effects and safety of arbitrary theme scripts, subprocess relaunch, optional dependency installation, runtime config isolation, non-Qt6 cross-platform compatibility.
