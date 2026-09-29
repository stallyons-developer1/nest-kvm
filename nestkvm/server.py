"""Server = the machine whose keyboard/mouse you physically use.

One mouse + one keyboard listener stay alive for the WHOLE connection. Switching
between LOCAL and REMOTE only flips whether they swallow events — we never stop
and restart them, because on macOS tearing down a suppressing event tap leaves it
behind, which keeps eating clicks and keys after control returns to this machine.

  LOCAL  — listeners pass everything through and only watch for the cursor
           hitting the edge that faces the other computer.
  REMOTE — the other computer is being driven: events are forwarded over the
           socket and swallowed here. We leave REMOTE when the client reports its
           cursor came back to the shared edge.

Relative motion differs by OS:
  * macOS — the on-screen cursor is frozen (CGAssociateMouseAndMouseCursorPosition)
    and we read true hardware deltas (kCGMouseEventDeltaX/Y) off the event tap via
    darwin_intercept. Position math can't work with a frozen cursor, and hardware
    deltas never glitch at a screen edge. pynput fires the high-level callbacks
    BEFORE the intercept, so clicks/scroll/keys still forward via on_* while the
    intercept swallows them from this Mac.
  * other — incremental position deltas, warping the cursor back to centre only
    near a real edge.
"""

import queue
import sys
import threading

from pynput import keyboard, mouse

from .protocol import Connection
from .screen import get_screen_size
from .keys import serialize_key


class Server:
    def __init__(self, conn: Connection, edge: str = "right",
                 clipboard: bool = True, images: bool = True, speed: float = 1.0,
                 edge_px: int = 2):
        self.conn = conn
        self.edge = edge  # which side the OTHER computer physically sits on
        self.width, self.height = get_screen_size()
        self.cx = self.width // 2
        self.cy = self.height // 2
        self.remote = False
        self.running = True
        self.speed = speed
        # crossing band: fire within this many px of the edge. A hard `x == 0`
        # check misses Retina's fractional coordinates (0.5, 1.3, ...), so the
        # jump to the other machine would trigger only sometimes.
        self._edge_px = max(1, edge_px)

        self.mouse_ctrl = mouse.Controller()
        self._m_listener = None
        self._k_listener = None
        self._last_pos = None       # last reported cursor pos, for incremental deltas
        self._sx = 0.0              # sub-pixel carry for speed scaling
        self._sy = 0.0
        self._margin = 60           # recenter only within this many px of a real edge
        self._pending_center = False
        self._pending_wait = 0
        self._cmd = queue.Queue()

        self._is_mac = sys.platform == "darwin"
        self._Q = None
        self._frozen = False
        if self._is_mac:
            import Quartz

            self._Q = Quartz
            self._MOVE_TYPES = {
                Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDragged,
                Quartz.kCGEventRightMouseDragged, Quartz.kCGEventOtherMouseDragged,
            }

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
        self._start_listeners()
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
            self.remote = False
            self._set_suppress(False)
            self._unfreeze()
            self._stop_listeners()
            if self.clip:
                self.clip.stop()

    def _enter_remote(self, ratio):
        self._last_pos = None  # first remote move re-establishes the baseline
        self._sx = self._sy = 0.0
        self._pending_center = False
        self._pending_wait = 0
        self.remote = True
        self._set_suppress(True)
        self._safe_send({"t": "enter", "edge": self.edge, "ratio": ratio})
        self.mouse_ctrl.position = (self.cx, self.cy)
        self._freeze()

    def _leave_remote(self, ratio):
        self.remote = False
        self._set_suppress(False)
        self._unfreeze()
        y = int(ratio * self.height)
        # drop the cursor clear of the crossing band so it doesn't instantly re-cross
        inset = self._edge_px + 12
        if self.edge == "right":
            self.mouse_ctrl.position = (self.width - 1 - inset, y)
        else:
            self.mouse_ctrl.position = (inset, y)

    # ---- macOS cursor freeze (decouples the pointer from the mouse) ----
    def _freeze(self):
        if self._is_mac and not self._frozen:
            self._Q.CGAssociateMouseAndMouseCursorPosition(False)
            self._frozen = True

    def _unfreeze(self):
        if self._is_mac and self._frozen:
            self._Q.CGAssociateMouseAndMouseCursorPosition(True)
            self._frozen = False

    # ---- listeners (persistent for the whole connection) ----
    def _start_listeners(self):
        mkw = {"darwin_intercept": self._darwin_intercept} if self._is_mac else {}
        kkw = {"darwin_intercept": self._darwin_intercept} if self._is_mac else {}
        self._m_listener = mouse.Listener(
            on_move=self._on_move, on_click=self._on_click,
            on_scroll=self._on_scroll, **mkw)
        self._k_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release, **kkw)
        self._m_listener.start()
        self._k_listener.start()

    def _stop_listeners(self):
        for listener in (self._m_listener, self._k_listener):
            if listener:
                listener.stop()
        self._m_listener = None
        self._k_listener = None

    def _set_suppress(self, on):
        # macOS ignores this — _darwin_intercept decides suppression instead.
        # On Windows the low-level hook reads this flag on every event.
        for listener in (self._m_listener, self._k_listener):
            if listener:
                listener._suppress = on

    def _darwin_intercept(self, event_type, event):
        if not self.remote:
            return event  # LOCAL: let everything through
        # REMOTE: mouse motion must be read HERE — the cursor is frozen, so the
        # on_move callback only ever sees the frozen position. Clicks/scroll/keys
        # are already forwarded by the on_* callbacks (they run before us).
        if event_type in self._MOVE_TYPES:
            Q = self._Q
            dx = Q.CGEventGetIntegerValueField(event, Q.kCGMouseEventDeltaX)
            dy = Q.CGEventGetIntegerValueField(event, Q.kCGMouseEventDeltaY)
            if dx or dy:
                self._emit_move(dx, dy)
        return None  # swallow everything from this Mac while driving the client

    # ---- callbacks (shared; each checks self.remote) ----
    def _on_move(self, x, y):
        if self.remote:
            if not self._is_mac:
                self._on_move_remote(x, y)  # mac motion comes from the intercept
            return
        if self.edge == "right" and x >= self.width - 1 - self._edge_px:
            self._cmd.put(("enter", y / self.height))
        elif self.edge == "left" and x <= self._edge_px:
            self._cmd.put(("enter", y / self.height))

    def _on_click(self, x, y, button, pressed):
        if self.remote:
            self._safe_send({"t": "down" if pressed else "up", "btn": button.name})

    def _on_scroll(self, x, y, dx, dy):
        if self.remote:
            self._safe_send({"t": "scroll", "dx": dx, "dy": dy})

    def _on_press(self, key):
        if self.remote:
            self._safe_send({"t": "kd", "key": serialize_key(key)})

    def _on_release(self, key):
        if self.remote:
            self._safe_send({"t": "ku", "key": serialize_key(key)})

    def _emit_move(self, dx, dy):
        self._sx += dx * self.speed
        self._sy += dy * self.speed
        sdx = int(self._sx)
        sdy = int(self._sy)
        self._sx -= sdx
        self._sy -= sdy
        if sdx or sdy:
            self._safe_send({"t": "move", "dx": sdx, "dy": sdy})

    def _on_move_remote(self, x, y):
        # non-macOS path: incremental position deltas, recenter only near an edge
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
            self._emit_move(dx, dy)
        if (x < self._margin or x > self.width - self._margin
                or y < self._margin or y > self.height - self._margin):
            self.mouse_ctrl.position = (self.cx, self.cy)
            self._pending_center = True
            self._pending_wait = 0
