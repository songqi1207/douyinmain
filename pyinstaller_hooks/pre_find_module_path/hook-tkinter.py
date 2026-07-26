"""Keep tkinter discoverable when PyInstaller cannot initialize host Tcl.

The release spec supplies the Tcl/Tk runtime files explicitly, so a broken
host-side Tcl library probe must not remove tkinter from the packaged helper.
"""


def pre_find_module_path(hook_api):
    # Deliberately keep the module search paths provided by PyInstaller.
    return None
