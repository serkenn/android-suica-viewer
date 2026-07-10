# -*- mode: python ; coding: utf-8 -*-
"""Builds suica-viewer and suica-viewer-gui as single-file executables.

Run from anywhere with:  pyinstaller packaging/suica-viewer.spec
"""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH is injected by PyInstaller and holds this file's directory.
PROJECT_ROOT = os.path.dirname(SPECPATH)  # noqa: F821

# nfcpy resolves its reader drivers through importlib.import_module(), so static
# analysis never sees nfc.clf.rcs380 and friends.
HIDDEN_IMPORTS = collect_submodules("nfc")

# station_code_lookup.py opens this via importlib.resources.files("suica_viewer").
DATAS = [(os.path.join(PROJECT_ROOT, "suica_viewer", "station_codes.csv"), "suica_viewer")]

# On Windows a console window would sit behind the Tk window for the whole session.
GUI_CONSOLE = sys.platform != "win32"


def analyze(entry_script):
    return Analysis(  # noqa: F821
        [os.path.join(SPECPATH, entry_script)],  # noqa: F821
        pathex=[PROJECT_ROOT],
        datas=DATAS,
        hiddenimports=HIDDEN_IMPORTS,
    )


def build_onefile(analysis, name, console):
    return EXE(  # noqa: F821
        PYZ(analysis.pure),  # noqa: F821
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name=name,
        console=console,
        # Stripping breaks code signatures on macOS, and UPX trips virus scanners.
        strip=False,
        upx=False,
    )


def assert_tcl_bundled(analysis):
    """Fail the build when the Tcl runtime is missing rather than shipping a broken GUI.

    PyInstaller only warns ("Library not found: could not resolve libtcl9.0.so") when it
    cannot locate the Tcl shared library next to _tkinter, then happily produces a binary
    that dies on `import tkinter`. The Tcl *data* files get collected either way, so the
    shared library is the thing worth checking. Interpreters that ship Tcl/Tk 9 (uv's
    managed CPython builds, for one) hit this unless their lib/ dir is on the loader path.
    """
    if not any("tcl" in dest.lower() for dest, _src, _kind in analysis.binaries):
        raise SystemExit(
            f"{name_gui}: no Tcl shared library was collected, so the built binary would "
            "crash on `import tkinter`. Build with an interpreter whose Tcl/Tk libraries "
            "the linker can resolve (see .github/workflows/release.yml)."
        )


name_cli = "suica-viewer"
name_gui = "suica-viewer-gui"

cli_exe = build_onefile(analyze("cli_entry.py"), name_cli, console=True)

gui_analysis = analyze("gui_entry.py")
assert_tcl_bundled(gui_analysis)
gui_exe = build_onefile(gui_analysis, name_gui, console=GUI_CONSOLE)
