"""macOS 14.4+/15 crash workaround.

On modern macOS, TISGetInputSourceProperty validates its argument by calling
islGetInputSourceListWithAdditions, which asserts it is running on the main
dispatch queue. pynput's keyboard layout build triggers this from a background
thread (the listener/injection thread), so once an NSApplication run loop is
active (our webview GUI) the app hits dispatch_assert_queue and crashes.

Calling the input-source enumeration once here, on the MAIN thread at startup,
warms the internal cache so the later off-thread calls reuse it and never
re-enumerate. Call this before any input listener/controller is used, from the
main thread.
"""

import sys


def warm_input_source():
    if sys.platform != "darwin":
        return
    try:
        import ctypes

        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        carbon.TISCreateInputSourceList.restype = ctypes.c_void_p
        carbon.TISCreateInputSourceList.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        carbon.TISCopyCurrentKeyboardInputSource.restype = ctypes.c_void_p
        # enumerate once on the main thread to populate the cache
        carbon.TISCreateInputSourceList(None, False)
        carbon.TISCopyCurrentKeyboardInputSource()
    except Exception:
        pass
