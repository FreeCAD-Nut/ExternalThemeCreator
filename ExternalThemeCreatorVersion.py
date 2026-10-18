"""Authoritative External Theme Creator version from FreeCAD package metadata."""
from pathlib import Path
import xml.etree.ElementTree as ET


def get_workbench_version() -> str:
    """Return the workbench version defined in package.xml."""
    metadata = Path(__file__).resolve().with_name("package.xml")
    root = ET.parse(metadata).getroot()
    element = root.find("{*}version")
    version = (element.text or "").strip() if element is not None else ""
    if not version:
        raise ValueError(f"Missing workbench version in {metadata}")
    return version
