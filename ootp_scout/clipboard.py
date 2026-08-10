"""Put text on the Windows clipboard without shelling out.

Deliberately not a PowerShell call: `Set-Clipboard` is fine, but reaching it
means either a .ps1 file (blocked by the default execution policy on a stock
Windows install) or spawning powershell.exe per run. The Win32 API is right
here and costs nothing.

Falls back to a no-op with a reason on any other platform, so callers can
report "not copied" rather than crash.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class ClipboardError(RuntimeError):
    pass


def _copy_windows(text: str) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    payload = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(payload)

    if not user32.OpenClipboard(None):
        raise ClipboardError("could not open the clipboard - another program "
                             "may be holding it open")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            raise ClipboardError("could not allocate clipboard memory")
        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            raise ClipboardError("could not lock clipboard memory")
        try:
            ctypes.memmove(locked, payload, size)
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            # Ownership only transfers on success; free it ourselves otherwise.
            kernel32.GlobalFree(handle)
            raise ClipboardError("the clipboard rejected the data")
    finally:
        user32.CloseClipboard()


def copy(text: str) -> None:
    """Put `text` on the clipboard. Raises ClipboardError if it cannot."""
    if sys.platform != "win32":
        raise ClipboardError(f"clipboard copying is not implemented on "
                             f"{sys.platform}")
    _copy_windows(text)
