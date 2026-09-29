"""Server = the machine whose keyboard/mouse you physically use.

Two modes, switched by a single manager thread (never inside a pynput callback,
which must stay lightweight):

  LOCAL  — the mouse/keyboard listeners pass everything through and only watch
           for the cursor hitting the edge that faces the other computer.
           Everything works normally on this machine. When the edge is reached
           we push ("enter", ...) to the queue.

  REMOTE — the other computer is being driven. The same listeners now swallow
           every event so nothing reaches THIS machine, and forward it over the
           socket. The cursor is warped back to screen-centre on
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
                 clipboard: bool = True, images: bool = True):
        self.conn = conn
        self.edge = edge  # which side the OTHER computer physically sits on
        self.width, self.height = get_screen_size()
        self.cx = self.width // 2
        self.cy = self.height // 2
        self.remote = False
        self.running = True

        self.mouse_ctrl = mouse.Controller()
        self._m_listener = None
        self._k_listener = None
        self._last_pos = None  # last reported cursor pos, for incremental deltas
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
            self._stop_listeners()
            if self.clip:
                self.clip.stop()

    def _enter_remote(self, ratio):
        self._last_pos = None  # first remote move re-establishes the baseline
        self.remote = True
        self._set_suppress(True)
        self._safe_send({"t": "enter", "edge": self.edge, "ratio": ratio})
        self.mouse_ctrl.position = (self.cx, self.cy)

    def _leave_remote(self, ratio):
        self.remote = False
        self._set_suppress(False)
        y = int(ratio * self.height)
        # drop the cursor just inside our edge so it doesn't instantly re-cross
        if self.edge == "right":
            self.mouse_ctrl.position = (self.width - 3, y)
        else:
            self.mouse_ctrl.position = (2, y)

    # ---- listeners ----
    # One mouse + one keyboard listener live for the whole connection; switching
    # modes only flips whether they swallow events. Stopping and restarting a
    # suppressing listener on macOS left its event tap behind, which kept eating
    # clicks and keys after control came back to this machine.
    def _start_listeners(self):
        self._m_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
            darwin_intercept=self._darwin_intercept,
        )
        self._k_listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            darwin_intercept=self._darwin_intercept,
        )
        self._m_listener.start()
        self._k_listener.start()

    def _stop_listeners(self):
        for listener in (self._m_listener, self._k_listener):
            if listener:
                listener.stop()
        self._m_listener = None
        self._k_listener = None

    def _set_suppress(self, on):
        # Windows: the low-level hook reads this flag on every event.
        # macOS: unused; _darwin_intercept decides instead.
        for listener in (self._m_listener, self._k_listener):
            if listener:
                listener._suppress = on

    def _darwin_intercept(self, event_type, event):
        # returning None swallows the event; returning it passes it through
        return None if self.remote else event

    # ---- callbacks ----
    def _on_move(self, x, y):
        if self.remote:
            self._on_move_remote(x, y)
        elif self.edge == "right" and x >= self.width - 1:
            self._cmd.put(("enter", y / self.height))
        elif self.edge == "left" and x <= 0:
            self._cmd.put(("enter", y / self.height))

    def _on_move_remote(self, x, y):
        if self._last_pos is None:
            self._last_pos = (x, y)
            return
        dx = x - self._last_pos[0]
        dy = y - self._last_pos[1]
        if dx == 0 and dy == 0:
            return  # our own warp-to-centre event, or no motion
        self._safe_send({"t": "move", "dx": dx, "dy": dy})
        # keep the physical cursor near centre so it never sticks to a real edge,
        # then read back where it actually landed so the next delta is correct
        # whether or not the warp took effect (it can be swallowed under suppress).
        self.mouse_ctrl.position = (self.cx, self.cy)
        self._last_pos = self.mouse_ctrl.position

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
