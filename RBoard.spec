# -*- mode: python ; coding: utf-8 -*-
# Portable R Board build: pyinstaller RBoard.spec --noconfirm
# Makes dist/R Board/ (a folder with R Board.exe) to zip and share.

import os
from os.path import join

from PyInstaller.utils.hooks import (
    collect_data_files, collect_dynamic_libs, collect_submodules)

from beeref import constants


a = Analysis(
    [join('beeref', '__main__.py')],
    pathex=[os.getcwd()],
    binaries=collect_dynamic_libs('onnxruntime'),
    datas=collect_data_files('beeref', includes=[
        '**/*.html', '**/*.png', '**/*.json', '**/*.npz', '**/*.ico']),
    hiddenimports=(collect_submodules('winrt')
                   + collect_submodules('beeref')
                   + ['onnxruntime', 'tokenizers']),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Developer tools that come along with the dependencies otherwise
    excludes=['tkinter', 'pytest', 'IPython', 'matplotlib', 'playwright'],
    noarchive=False)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=constants.APPNAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=join('beeref', 'assets', 'logo.ico'))

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=constants.APPNAME)
