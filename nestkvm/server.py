"""Server = the machine whose keyboard/mouse you physically use.

Two modes, switched by a single manager thread (never inside a pynput callback,
which must stay lightweight):

  LOCAL  — one non-suppressing mouse listener watches for the cursor hitting the
           edge that faces the other computer. Everything works normally on this
           machine. When the edge is reached we push ("enter", ...) to the queue.

  REMOTE — the other computer is being driven. We start suppressing mouse +
           keyboard listeners so nothing reaches THIS machine, and forward every
           event over the socket. The cursor is warped back to screen-centre on
           every move so it never gets stuck against a real screen edge; the
           delta from centre is what we send. We leave REMOTE when the client
           reports its cursor came back to the shared edge.

Warp-to-centre note: Controller.position uses CGWarpMouseCursorPosition (macOS) /
SetCursorPos (Windows), which bypass the event tap/hook, so the warp still works
even while moves are suppressed.
"""

import queue
import threading

from pynput import keyboard, mouse

from .protocol import Connection
from .screen import get_screen_size
from .keys import serialize_key


class Server:
    def __init__(self, conn: Connection, edge: str = "right",
                 clipboard: bool = True, images: bool = True, speed: float = 1.0):
        self.conn = conn
        self.edge = edge  # which side the OTHER computer physically sits on
        self.width, self.height = get_screen_size()
        self.cx = self.width // 2
        self.cy = self.height // 2
        self.remote = False
        self.running = True
        self.speed = speed

        self.mouse_ctrl = mouse.Controller()
        self._m_listener = None
        self._k_listener = None
        self._last_pos = None       # last reported cursor pos, for incremental deltas
        self._sx = 0.0              # sub-pixel carry for speed scaling
        self._sy = 0.0
        self._margin = 60           # recenter only within this many px of a real edge
        self._pending_center = False  # waiting for the cursor to land back near centre
        self._pending_wait = 0
        self._cmd = queue.Queue()

        self.clip = None
        if clipboard:
            from .clipboard import ClipboardSync

            self.clip = ClipboardSync(self._safe_send, images=images)

    # ---- lifecycle ----
    def run(self):
        threading.Thread(target=self._reader_loop, daemon=True).start()
        if self.clip:
            self.clip.start()
        self._manage()  # blocks until the connection drops or stop()

    def stop(self):
        self.running = False
        self._cmd.put(None)

    # ---- inbound messages from the client ----
    def _reader_loop(self):
        try:
            while self.running:
                msg = self.conn.read()
                if msg is None:
                    break
                t = msg.get("t")
                if t == "leave":
                    self._cmd.put(("leave", msg.get("ratio", 0.5)))
                elif t == "clip" and self.clip:
                    self.clip.apply_remote(msg.get("text", ""))
                elif t == "clip_img" and self.clip:
                    self.clip.apply_remote_img(msg.get("png", ""))
        finally:
            self.running = False
            self._cmd.put(None)

    def _safe_send(self, msg):
        try:
            self.conn.send(msg)
        except OSError:
            self.running = False
            self._cmd.put(None)

    # ---- mode manager (own thread) ----
    def _manage(self):
        self._start_local()
        try:
            while self.running:
                cmd = self._cmd.get()
                if cmd is None:
                    break
                if cmd[0] == "enter" and not self.remote:
                    self._enter_remote(cmd[1])
                elif cmd[0] == "leave" and self.remote:
                    self._leave_remote(cmd[1] if len(cmd) > 1 else 0.5)
        finally:
            self._stop_local()
            self._stop_remote()
            if self.clip:
                self.clip.stop()

    def _enter_remote(self, ratio):
        self.remote = True
        self._safe_send({"t": "enter", "edge": self.edge, "ratio": ratio})
        self._stop_local()
        self.mouse_ctrl.position = (self.cx, self.cy)
        self._last_pos = None  # first remote move re-establishes the baseline
        self._sx = self._sy = 0.0
        self._pending_center = False
        self._pending_wait = 0
        self._start_remote()

    def _leave_remote(self, ratio):
        self.remote = False
        self._stop_remote()
        y = int(ratio * self.height)
        # drop the cursor just inside our edge so it doesn't instantly re-cross
        if self.edge == "right":
            self.mouse_ctrl.position = (self.width - 3, y)
        else:
            self.mouse_ctrl.position = (2, y)
        self._start_local()

    # ---- listeners ----
    def _start_local(self):
        self._m_listener = mouse.Listener(on_move=self._on_move_local)
        self._m_listener.start()

    def _stop_local(self):
        if self._m_listener:
            self._m_listener.stop()
            self._m_listener = None

    def _start_remote(self):
        self._m_listener = mouse.Listener(
            on_move=self._on_move_remote,
            on_click=self._on_click_remote,
            on_scroll=self._on_scroll_remote,
            suppress=True,
        )
        self._m_listener.start()
        self._k_listener = keyboard.Listener(
            on_press=self._on_press_remote,
            on_release=self._on_release_remote,
            suppress=True,
        )
        self._k_listener.start()

    def _stop_remote(self):
        if self._m_listener:
            self._m_listener.stop()
            self._m_listener = None
        if self._k_listener:
            self._k_listener.stop()
            self._k_listener = None

    # ---- LOCAL callbacks ----
    def _on_move_local(self, x, y):
        if self.remote:
            return
        if self.edge == "right" and x >= self.width - 1:
            self._cmd.put(("enter", y / self.height))
        elif self.edge == "left" and x <= 0:
            self._cmd.put(("enter", y / self.height))

    # ---- REMOTE callbacks ----
    def _on_move_remote(self, x, y):
        # After a recenter we drop events until the cursor is actually back near
        # centre, so the warp discontinuity is never measured as motion. The
        # counter is a safety net in case the warp event is never observed.
        if self._pending_center:
            self._pending_wait += 1
            near = abs(x - self.cx) <= self._margin and abs(y - self.cy) <= self._margin
            if near or self._pending_wait > 20:
                self._pending_center = False
                self._pending_wait = 0
                self._last_pos = (x, y)
            return
        if self._last_pos is None:
            self._last_pos = (x, y)
            return
        dx = x - self._last_pos[0]
        dy = y - self._last_pos[1]
        self._last_pos = (x, y)
        if dx or dy:
            self._sx += dx * self.speed
            self._sy += dy * self.speed
            sdx = int(self._sx)
            sdy = int(self._sy)
            self._sx -= sdx
            self._sy -= sdy
            if sdx or sdy:
                self._safe_send({"t": "move", "dx": sdx, "dy": sdy})
        # only recenter when nearing a real screen edge, so most moves are pure
        # incremental deltas with no warp discontinuity
        if (x < self._margin or x > self.width - self._margin
                or y < self._margin or y > self.height - self._margin):
            self.mouse_ctrl.position = (self.cx, self.cy)
            self._pending_center = True
            self._pending_wait = 0

    def _on_click_remote(self, x, y, button, pressed):
        self._safe_send({"t": "down" if pressed else "up", "btn": button.name})

    def _on_scroll_remote(self, x, y, dx, dy):
        self._safe_send({"t": "scroll", "dx": dx, "dy": dy})

    def _on_press_remote(self, key):
        self._safe_send({"t": "kd", "key": serialize_key(key)})

    def _on_release_remote(self, key):
        self._safe_send({"t": "ku", "key": serialize_key(key)})
