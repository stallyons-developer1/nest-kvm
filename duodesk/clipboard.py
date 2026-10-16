"""Bidirectional clipboard sync (text + images) via polling.

Runs on BOTH ends. Each side watches its own clipboard; on change it pushes the
content to the peer, who writes it into its own clipboard.

Text: via pyperclip.
Images: via Pillow (read) + a per-OS write (osascript on macOS, PowerShell on
Windows). Image change is tracked by a pixel signature (downscaled grayscale
hash) instead of raw PNG bytes, because the OS clipboard re-encodes PNGs on
round-trip and byte hashes would bounce forever.

Critical rule learned the hard way: when the clipboard holds an image (or files),
pyperclip returns "" / None. We must NOT sync that as text, or we wipe the peer's
clipboard and bounce a literal "None" string around.
"""

import base64
import hashlib
import io
import subprocess
import sys
import tempfile
import threading
import time

try:
    import pyperclip

    _HAVE_TEXT = True
except Exception:
    _HAVE_TEXT = False

try:
    from PIL import Image, ImageGrab

    _HAVE_IMG = True
except Exception:
    _HAVE_IMG = False


def _img_signature(img) -> str:
    small = img.convert("L").resize((32, 32))
    return hashlib.md5(small.tobytes()).hexdigest()


class ClipboardSync(threading.Thread):
    def __init__(self, send, interval: float = 0.5, images: bool = True):
        super().__init__(daemon=True)
        self.send = send
        self.interval = interval
        self.images = images and _HAVE_IMG
        self.running = True
        self._last_text = None
        self._last_img = None
        if _HAVE_TEXT:
            try:
                t = pyperclip.paste()
                self._last_text = t if isinstance(t, str) else None
            except Exception:
                self._last_text = None

    def run(self):
        while self.running:
            try:
                self._poll()
            except Exception:
                pass
            time.sleep(self.interval)

    def _poll(self):
        cur = None
        if _HAVE_TEXT:
            try:
                cur = pyperclip.paste()
            except Exception:
                cur = None
        has_text = isinstance(cur, str) and cur != ""
        if has_text:
            if cur != self._last_text:
                self._last_text = cur
                self.send({"t": "clip", "text": cur})
            return  # text is on the clipboard; don't probe for an image
        # no text -> an image may have been copied
        if self.images:
            img = None
            try:
                img = ImageGrab.grabclipboard()
            except Exception:
                img = None
            if isinstance(img, Image.Image):
                sig = _img_signature(img)
                if sig != self._last_img:
                    self._last_img = sig
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    self.send({
                        "t": "clip_img",
                        "png": base64.b64encode(buf.getvalue()).decode("ascii"),
                    })

    # ---- inbound from peer ----
    def apply_remote(self, text):
        if not _HAVE_TEXT or not isinstance(text, str) or text == "":
            return
        self._last_text = text  # set before copy so our own poll won't re-send it
        try:
            pyperclip.copy(text)
        except Exception:
            pass

    def apply_remote_img(self, png_b64):
        if not self.images or not png_b64:
            return
        try:
            data = base64.b64decode(png_b64)
            img = Image.open(io.BytesIO(data))
            self._last_img = _img_signature(img)  # echo guard
        except Exception:
            return
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(data)
                path = f.name
            self._write_image_to_clipboard(path)
        except Exception:
            pass

    def _write_image_to_clipboard(self, path):
        if sys.platform == "darwin":
            script = ('set the clipboard to '
                      '(read (POSIX file "%s") as «class PNGf»)' % path)
            subprocess.run(["osascript", "-e", script], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform.startswith("win"):
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "$img=[System.Drawing.Image]::FromFile('%s');"
                "[System.Windows.Forms.Clipboard]::SetImage($img);"
                "$img.Dispose()"
            ) % path
            subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", ps],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    def stop(self):
        self.running = False
