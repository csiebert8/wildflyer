# PyInstaller recipe for the AUSL Schedule Solver desktop app.
#
# Build (from the repository root):  pyinstaller packaging/ausl_solver.spec --noconfirm
# macOS: produces dist/AUSL Schedule Solver.app   Other systems: dist/AUSL Schedule Solver/
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is provided by PyInstaller)
SRC = ROOT / "src" / "wildflyer"
NAME = "AUSL Schedule Solver"

datas = [
    (str(SRC / "app.py"), "wildflyer"),  # Streamlit runs the page script from a file
    (str(SRC / "assets"), "wildflyer/assets"),
    (str(ROOT / "examples" / "ausl_2027.xlsx"), "wildflyer/examples"),
]
binaries = []
hiddenimports = collect_submodules("wildflyer")

# Streamlit and OR-Tools load files, native libraries and modules dynamically.
for package in ("streamlit", "ortools"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
for package in ("streamlit", "openpyxl", "pandas", "pyarrow", "altair"):
    datas += copy_metadata(package)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "desktop_main.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
icon = str(SRC / "assets" / "ausl_logo.png")
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=sys.platform != "darwin",  # the Mac app has no Terminal window
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{NAME}.app",
        icon=icon,
        bundle_identifier="com.auprosports.schedulesolver",
        info_plist={
            "CFBundleDisplayName": NAME,
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
