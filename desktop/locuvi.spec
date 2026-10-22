# PyInstaller recipe for the Locuvi desktop app (Windows, macOS; Linux for testing).
# Build from this folder after `npm run build` in ../frontend:
#     pyinstaller --noconfirm locuvi.spec
# Result: dist/Locuvi/ (Windows, Linux) or dist/Locuvi.app (macOS).
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = Path(SPECPATH)  # noqa: F821 - provided by PyInstaller
ROOT = HERE.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "dist"
if not (FRONTEND / "index.html").is_file():
    raise SystemExit("Build the web app first: cd frontend && npm ci && npm run build")

datas = [
    (str(FRONTEND), "frontend"),
    # Alembic reads the migration scripts from disk, so they ship as files
    (str(BACKEND / "locuvi" / "migrations"), "locuvi/migrations"),
    (str(BACKEND / "locuvi" / "pdf" / "fonts"), "locuvi/pdf/fonts"),
    (str(HERE / "assets" / "locuvi.png"), "desktop/assets"),
]
for pkg in ("reportlab", "tzdata", "certifi", "svglib", "anthropic"):
    datas += collect_data_files(pkg)

hidden = collect_submodules("locuvi") + collect_submodules("uvicorn") + [
    "tzdata", "multipart", "python_multipart", "email.mime.multipart", "sqlite3",
]

a = Analysis(  # noqa: F821
    [str(HERE / "locuvi_desktop.py")],
    pathex=[str(BACKEND)],
    datas=datas,
    hiddenimports=hidden,
    excludes=["pytest", "IPython", "matplotlib", "numpy.tests"],
)
pyz = PYZ(a.pure)  # noqa: F821
icon = str(HERE / "assets" / ("locuvi.icns" if sys.platform == "darwin" else "locuvi.ico"))
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Locuvi",
    console=False,  # no black console window; the app shows its own small window
    icon=icon,
    target_arch=None,
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Locuvi")  # noqa: F821
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="Locuvi.app",
        icon=icon,
        bundle_identifier="uk.locuvi.desktop",
        info_plist={
            "CFBundleName": "Locuvi",
            "CFBundleDisplayName": "Locuvi",
            "CFBundleShortVersionString": os.environ.get("LOCUVI_VERSION", "1.0.0"),
            "CFBundleVersion": os.environ.get("LOCUVI_VERSION", "1.0.0"),
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": "Locuvi · AGPL-3.0",
        },
    )
