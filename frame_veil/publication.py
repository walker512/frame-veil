"""Optional no-replace publication of a complete silent-render bundle.

Trusted, stable parent directories only. Not crash durability or a hostile-user sandbox.
"""
import ctypes
import os
from pathlib import Path
import stat
import sys
import tempfile
from . import core


def _rename_function():
    if sys.platform == 'win32':
        # Windows rename refuses an existing destination; no overwrite fallback.
        return None
    if not sys.platform.startswith('linux'):
        raise core.Invalid('Staged publication is unsupported on this platform.')
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError):
        raise core.Invalid('No no-replace rename capability.') from None
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    return function


def rename_exclusive(source, destination):
    function = _rename_function()
    if sys.platform == 'win32':
        os.rename(source, destination)
    elif function(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        raise OSError(code, 'No-replace publication failed')


def _destination(out):
    _rename_function()  # Fail before expensive work when the primitive is absent.
    path = Path(out).absolute()
    if os.path.lexists(path):
        raise FileExistsError('Destination already exists')
    if not path.parent.is_dir():
        raise core.Invalid('Destination parent must already exist.')
    return path


def publish_render(staged, out):
    """Verify then move an existing complete bundle without re-encoding.

    The caller must trust the source and both parent directories, including during
    verification. A matching receipt is not source authenticity or human approval.
    """
    destination = _destination(out)
    source = Path(staged).absolute()
    if not stat.S_ISDIR(source.lstat().st_mode):
        raise core.Invalid('A regular staged bundle directory is required.')
    result = core.verify(source)
    # Do not copy on EXDEV, replace any destination, or delete anything on failure.
    rename_exclusive(source, destination)
    return result


def render_staged(source, plan, out):
    destination = _destination(out)
    # Sibling staging avoids cross-device publication in the normal path.
    # Retain all staging on failure/cancellation. Never recursively delete it:
    # another process may have added files. An empty wrapper remains on success.
    wrapper = Path(tempfile.mkdtemp(prefix='.frame-veil-stage-', dir=destination.parent))
    bundle = wrapper / 'bundle'
    result = core.render(source, plan, bundle)
    publish_render(bundle, destination)
    return result
