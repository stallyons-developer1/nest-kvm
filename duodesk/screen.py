"""Primary-display pixel size, per platform.

Used for edge detection (server) and cursor clamping (client). We try the
native OS call first, then screeninfo if installed, then a safe default.
"""

import sys


def get_screen_size():
    try:
        if sys.platform == "darwin":
            import Quartz  # ships with pynput's pyobjc dependency

            main = Quartz.CGMainDisplayID()
            return (int(Quartz.CGDisplayPixelsWide(main)),
                    int(Quartz.CGDisplayPixelsHigh(main)))
        if sys.platform.startswith("win"):
            import ctypes

            user32 = ctypes.windll.user32
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
            return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    except Exception:
        pass

    try:
        from screeninfo import get_monitors

        m = get_monitors()[0]
        return (m.width, m.height)
    except Exception:
        return (1920, 1080)
