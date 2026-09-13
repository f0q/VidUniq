# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: сборка VidUniq.app с бандловым ffmpeg.
import os
import re
import sys

ROOT = os.path.abspath(SPECPATH)
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "viduniq", "__init__.py")).read()).group(1)
IS_MAC = sys.platform == "darwin"

binaries = []
for tool in ("ffmpeg", "ffprobe"):
    p = os.path.join(ROOT, "vendor", "ffmpeg", tool + (".exe" if sys.platform.startswith("win") else ""))
    if os.path.exists(p):
        binaries.append((p, "ffmpeg"))

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=[(os.path.join(ROOT, "viduniq", "resources"), os.path.join("viduniq", "resources"))],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Лишние модули Qt — уменьшают бандл в разы
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtNfc",
        "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "PySide6.QtSerialBus", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
        "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtNetworkAuth", "PySide6.QtHttpServer",
        "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtWebView", "PySide6.QtDesigner",
        "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtSvgWidgets", "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio", "PySide6.QtGraphs",
        "PySide6.QtGraphsWidgets", "PySide6.QtAsyncio", "PySide6.QtConcurrent", "PySide6.QtDBus",
        "PySide6.QtPrintSupport", "PySide6.QtXml",
        "tkinter", "unittest", "pydoc", "doctest", "test",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VidUniq",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64" if IS_MAC else None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "viduniq", "resources", "icon.icns" if IS_MAC else "icon.png"),
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="VidUniq",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="VidUniq.app",
        icon=os.path.join(ROOT, "viduniq", "resources", "icon.icns"),
        bundle_identifier="com.f0q.viduniq",
        version=VERSION,
        info_plist={
            "CFBundleName": "VidUniq",
            "CFBundleDisplayName": "VidUniq",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "12.0",
            "LSApplicationCategoryType": "public.app-category.video",
            "NSHumanReadableCopyright": "Форк Video-Uniqueizer (0xd5f). VidUniq © f0q",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Video",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": ["public.movie", "com.compuserve.gif"],
                "LSHandlerRank": "Alternate",
            }],
        },
    )
