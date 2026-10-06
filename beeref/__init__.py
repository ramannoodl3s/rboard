import os
import sys


def _prefer_system_msvc_runtime():
    """Load Windows' own (current) Microsoft C++ runtime before Qt.

    PyQt6 bundles an older msvcp140.dll (14.26). Whichever copy loads
    first is used by everything in the process, and ONNX Runtime (R
    Board's content model) crashes with the old one. The runtime is
    backwards compatible, so Qt runs fine on the newer system copy.
    """
    if sys.platform != 'win32':
        return
    import ctypes
    system = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                          'System32')
    for name in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll',
                 'msvcp140_1.dll', 'msvcp140_2.dll'):
        path = os.path.join(system, name)
        if os.path.isfile(path):
            try:
                ctypes.WinDLL(path)
            except OSError:
                pass


_prefer_system_msvc_runtime()
