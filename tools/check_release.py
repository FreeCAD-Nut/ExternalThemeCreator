"""Pure-Python static addon packaging checks; no FreeCAD installation needed."""
from pathlib import Path
import ast, xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
assert (root / "InitGui.py").is_file()
assert (root / "Init.py").is_file()
manifest = ET.parse(root / "package.xml").getroot()
ns = {"p": "https://wiki.freecad.org/Package_Metadata"}
assert manifest.findtext("p:version", namespaces=ns) == "0.9.85"
assert manifest.findtext("p:icon", namespaces=ns) == "Resources/icons/ETC_export.svg"
assert manifest.findtext("p:content/p:workbench/p:classname", namespaces=ns) == "ExternalThemeCreatorWorkbench"
for icon in manifest.findall(".//p:icon", ns):
    assert (root / icon.text).is_file(), icon.text
for p in root.rglob("*.py"):
    ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
for p in (root / "Resources/icons").glob("*.svg"):
    ET.parse(p)
assert not list(root.rglob("*.pyc"))
assert not list(root.rglob("__pycache__"))
print("PASS: manifest, workbench name, icons, SVG syntax, Python parsing, clean source")
