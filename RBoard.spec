# -*- mode: python ; coding: utf-8 -*-
# Portable R Board build: pyinstaller RBoard.spec --noconfirm
# Makes dist/R Board/ (a folder with R Board.exe) to zip and share.

import os
from os.path import join

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

from beeref import constants


def use_current_cpp_runtime():
    """PyQt6 ships an old Microsoft C++ runtime (14.26) that crashes ONNX
    Runtime (the content model). Put Windows' current copy in its place
    so the build (and the app it makes) uses the new one everywhere. The
    runtime is backwards compatible and may be shipped with apps."""
    import shutil
    import PyQt6
    qt_bin = join(os.path.dirname(PyQt6.__file__), 'Qt6', 'bin')
    system = join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')
    for name in ('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll'):
        bundled, current = join(qt_bin, name), join(system, name)
        if os.path.isfile(bundled) and os.path.isfile(current) and \
                os.path.getsize(bundled) != os.path.getsize(current):
            if not os.path.exists(bundled + '.orig'):
                shutil.copyfile(bundled, bundled + '.orig')
            shutil.copyfile(current, bundled)


use_current_cpp_runtime()


def standard_library():
    """All of Python's standard library, so plugins can use any of it
    (the build otherwise only keeps what R Board itself imports)."""
    import sys
    from importlib.util import find_spec
    skip = {'tkinter', 'turtle', 'turtledemo', 'idlelib', 'test',
            'lib2to3', 'ensurepip', 'venv', 'distutils', 'pydoc_data',
            'msilib', 'antigravity', 'this', '__phello__', 'curses'}
    names = []
    for name in sorted(sys.stdlib_module_names - skip):
        try:
            if find_spec(name) is None:
                continue
        except (ImportError, ValueError):
            continue
        names += collect_submodules(
            name, filter=lambda n: not any(
                part in ('test', 'tests', 'idle_test')
                for part in n.split('.')))
    return names

a = Analysis(
    [join('beeref', '__main__.py')],
    pathex=[os.getcwd()],
    binaries=[],
    datas=collect_data_files('beeref', includes=[
        '**/*.html', '**/*.png', '**/*.json', '**/*.npz', '**/*.ico']),
    hiddenimports=(collect_submodules('winrt')
                   + collect_submodules('beeref')
                   + standard_library()),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Developer tools that come along with the dependencies otherwise,
    # and the AI libraries, which come in the AI features plugin
    excludes=['tkinter', 'pytest', 'IPython', 'matplotlib', 'playwright',
              'onnxruntime', 'tokenizers', 'huggingface_hub'],
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
