"""Client = the machine being driven.

It never captures its own input; it only injects what the server sends. We track
the injected cursor position ourselves (rx, ry) by accumulating the deltas, so we
can tell when the cursor has walked back to the shared edge and hand control back
to the server with a "leave" message.
"""

from pynput import keyboard, mouse

from .protocol import Connection
from .screen import get_screen_size
from .keys import deserialize_button, deserialize_key


class Client:
    def __init__(self, conn: Connection, clipboard: bool = True, images: bool = True,
                 speed: float = 1.0, debug: bool = False):
        self.conn = conn
        self.debug = debug
        self._moves = 0
        self.width, self.height = get_screen_size()
        self.mouse_ctrl = mouse.Controller()
        self.kbd_ctrl = keyboard.Controller()
        self.active = False
        self.edge = "right"
        self.rx = 0
        self.ry = 0
        self.speed = speed
        self._fx = 0.0  # sub-pixel carry so slow speeds stay smooth
        self._fy = 0.0
        self.running = True

        self.clip = None
        if clipboard:
            from .clipboard import ClipboardSync

            self.clip = ClipboardSync(self._safe_send, images=images)

    def run(self):
        if self.clip:
            self.clip.start()
        try:
            while self.running:
                msg = self.conn.read()
                if msg is None:
                    break
                self._handle(msg)
        finally:
            self.running = False
            if self.clip:
                self.clip.stop()
            print("[nest-kvm] connection closed")

    def stop(self):
        self.running = False
        self.conn.close()

    def _safe_send(self, msg):
        try:
            self.conn.send(msg)
        except OSError:
            self.running = False

    def _place(self):
        self.mouse_ctrl.position = (int(self.rx), int(self.ry))

    def _leave(self):
        self.active = False
        if self.debug:
            print(f"[dbg] LEAVE: cursor reached the return edge (rx={self.rx:.0f}), "
                  f"handing control back to server", flush=True)
        self._safe_send({"t": "leave", "ratio": self.ry / self.height})

    def _handle(self, msg):
        t = msg.get("t")
        if t == "enter":
            self.active = True
            self._moves = 0
            self.edge = msg.get("edge", "right")
            ratio = msg.get("ratio", 0.5)
            # enter from the side facing the server, a margin clear of the return
            # edge so a small delta doesn't instantly cross back
            margin = 25
            self.rx = margin if self.edge == "right" else self.width - 1 - margin
            self.ry = int(ratio * self.height)
            self._fx = self._fy = 0.0
            self._place()
            if self.debug:
                print(f"[dbg] ENTER: server handed control here (edge={self.edge})", flush=True)
        elif t == "move":
            if not self.active:
                return
            if self.debug:
                self._moves += 1
                if self._moves <= 3:
                    print(f"[dbg] move #{self._moves}: dx={msg.get('dx')} dy={msg.get('dy')} "
                          f"rx={self.rx:.0f}", flush=True)
                elif self._moves % 40 == 0:
                    print(f"[dbg] receiving motion ({self._moves})", flush=True)
            self._fx += msg.get("dx", 0) * self.speed
            self._fy += msg.get("dy", 0) * self.speed
            step_x = int(self._fx)
            step_y = int(self._fy)
            self._fx -= step_x
            self._fy -= step_y
            self.rx += step_x
            self.ry += step_y
            if self.edge == "right" and self.rx <= 0:
                self._leave()
                return
            if self.edge == "left" and self.rx >= self.width - 1:
                self._leave()
                return
            self.rx = max(0, min(self.width - 1, self.rx))
            self.ry = max(0, min(self.height - 1, self.ry))
            self._place()
        elif t == "down":
            self.mouse_ctrl.press(deserialize_button(msg.get("btn", "left")))
        elif t == "up":
            self.mouse_ctrl.release(deserialize_button(msg.get("btn", "left")))
        elif t == "scroll":
            self.mouse_ctrl.scroll(msg.get("dx", 0), msg.get("dy", 0))
        elif t == "kd":
            k = deserialize_key(msg.get("key"))
            if k is not None:
                try:
                    self.kbd_ctrl.press(k)
                except Exception:
                    pass
        elif t == "ku":
            k = deserialize_key(msg.get("key"))
            if k is not None:
                try:
                    self.kbd_ctrl.release(k)
                except Exception:
                    pass
        elif t == "clip" and self.clip:
            self.clip.apply_remote(msg.get("text", ""))
        elif t == "clip_img" and self.clip:
            self.clip.apply_remote_img(msg.get("png", ""))
