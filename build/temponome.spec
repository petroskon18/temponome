# PyInstaller recipe for Temponome.app (Apple Silicon). Run via build/build_pkg.sh.
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "app", "temponome_app.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "ui"), "ui")],
    hiddenimports=["temponome", "tapo"],
    excludes=["scipy", "tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Temponome",
          console=False, target_arch="arm64", codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Temponome")
app = BUNDLE(
    coll,
    name="Temponome.app",
    icon=os.path.join(ROOT, "assets", "Temponome.icns"),
    bundle_identifier="local.temponome.app",
    version="1.0",
    info_plist={
        "CFBundleName": "Temponome",
        "CFBundleDisplayName": "Temponome",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.music",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Temponome listens to the music to find the beat.",
        "NSCameraUsageDescription": "Used only for timing calibration. The video stays on this Mac.",
        "NSLocalNetworkUsageDescription": "Temponome finds and controls your lights on your Wi-Fi.",
        "NSBonjourServices": [],
    },
)
