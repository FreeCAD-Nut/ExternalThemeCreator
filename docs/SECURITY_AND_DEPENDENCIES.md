# Security and dependencies

## Important user-facing capabilities

This addon is a theme creation and execution tool; **external themes can contain Python scripts**. Applying a theme from an untrusted source may execute arbitrary code with the same permissions as FreeCAD. Theme-license acceptance is not a security sandbox. Warn users prominently and avoid silently auto-enabling scripts from untrusted themes.

The source also contains functionality to create/manage shortcuts, launch additional FreeCAD processes, isolate runtime configuration, write generated config/macros, unpack theme archives, and remove temporary runtime directories. These are legitimate feature-specific operations but must be evaluated through the test plan; *source inspection alone does not prove all paths safe*.

## Network

- Inspector can search online FreeCAD source code; this is an explicit user option whose default is `False` (`AllowOnlineSearch`).
- Theme import features can retrieve content from supported remote sources; review sources and trust before import.
- Optional signing/encryption feature can download dependencies using PyPI HTTPS with a confirmation dialog. Windows PowerShell is used for some downloads. The implementation checks wheel/file metadata; verify hashes and install destinations in a network-enabled integration test.

## Python packages

The main workbench imports FreeCAD and the Qt APIs shipped with FreeCAD. For cryptographic features: `cryptography`, `cffi`, and `pycparser` can be installed in a private user folder after confirmation. FreeCAD Addon Manager dependency declaration/installer policy should be discussed with FreeCAD reviewers; **do not add a blanket requirements.txt** that would cause dependency installation at basic addon install time without review.

## Platform support

Windows contains explicitly platform-specific relaunch, PowerShell and shortcut logic. Linux AppImage and macOS Intel launch workflows have undergone real-world testing. The maintainer also completed Apple Silicon testing for v0.9.86. Other packaging and FreeCAD/Qt/Python combinations still require independent validation; document exact versions for reproducibility.

## Publication review gates

1. Confirm the person/entity that owns copyright of the complete code and all supplied SVGs, plus permission to publish under declared open-source license.
2. Inspect the entire binary dependency installation and remote-theme import path for extraction/path traversal, download integrity, executable launch, and files deleted.
3. Test that merely loading the workbench has no unsolicited network requests or user-profile changes (apart from FreeCAD normal GUI registration).
4. Test opt-in behavior and warnings for executing a theme's Python scripts, particularly downloaded themes.
5. Test clean uninstall and recovery from interrupted restart/dependency installation.
