# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
from mc_updater import __version__

datas = [("ui_dist", "ui_dist")]
binaries = []
hiddenimports = [
    "mc_updater",
    "mc_updater.api.js_api",
    "mc_updater.core.models",
    "mc_updater.core.hashing",
    "mc_updater.core.versioning",
    "mc_updater.core.config",
    "mc_updater.clients.http_client",
    "mc_updater.clients.modrinth",
    "mc_updater.clients.curseforge",
    "mc_updater.clients.loader_meta",
    "mc_updater.parsers.input_detector",
    "mc_updater.parsers.instance_meta",
    "mc_updater.parsers.jar_metadata",
    "mc_updater.parsers.mod_identifier",
    "mc_updater.resolver.upgrade_matcher",
    "mc_updater.resolver.dependency_resolver",
    "mc_updater.downloader.download_manager",
    "mc_updater.exporter.overrides_collector",
    "mc_updater.exporter.backup_exporter",
    "mc_updater.exporter.mrpack_exporter",
]

for pkg in ("webview", "pythonnet", "clr_loader"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["mc_updater\\main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"MC整合包升级助手-v{__version__}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="..\\assets\\app.ico",
)
