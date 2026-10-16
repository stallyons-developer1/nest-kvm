"""A tkinter front-end for DuoDesk with a sci-fi HUD look.

Everything is painted on one Canvas: dark teal background, neon-cyan beveled
(cut-corner) panels, corner hatch marks, and a cyan action button. The real
input widgets (combobox / entry / radios / log) are dark-themed and placed on
top of the canvas. The networking logic runs on a background thread, exactly as
the terminal commands do.
"""

import socket
import threading
import tkinter as tk
from tkinter import ttk

from .protocol import Connection

PORT_DEFAULT = 24800
W, H = 500, 600

# HUD palette
BG = "#06201f"
PANEL = "#0a2b29"
HEADER = "#0e3b37"
CYAN = "#2fe6d6"
CYAN_DK = "#139f93"
GLOW = "#063e3a"
TEXT = "#bdeee8"
MUTED = "#5f9e97"
AMBER = "#f5a623"
RED = "#ff5d5d"
GREEN = "#39e697"

MONO = "Courier New"


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def bevel(x0, y0, x1, y1, c):
    """Octagon points for a rectangle with chamfered (cut) corners."""
    return [x0 + c, y0, x1 - c, y0, x1, y0 + c, x1, y1 - c,
            x1 - c, y1, x0 + c, y1, x0, y1 - c, x0, y0 + c]


class App:
    def __init__(self, root):
        self.root = root
        root.title("DuoDesk")
        root.resizable(False, False)
        root.configure(bg=BG)

        self.running = False
        self.worker = None
        self.server_sock = None
        self.instance = None

        self.mode = tk.StringVar(value="server")
        self.edge = tk.StringVar(value="right")
        self.host = tk.StringVar(value="")
        self.port = tk.StringVar(value=str(PORT_DEFAULT))
        self.speed = tk.StringVar(value="0.5")

        self._init_style()
        self.c = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
        self.c.pack()
        self._draw_chrome()
        self._build_widgets()
        self._draw_button()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._sync()

    # ---- theming for the ttk inputs ----
    def _init_style(self):
        r = self.root
        r.option_add("*TCombobox*Listbox.background", PANEL)
        r.option_add("*TCombobox*Listbox.foreground", CYAN)
        r.option_add("*TCombobox*Listbox.selectBackground", CYAN_DK)
        r.option_add("*TCombobox*Listbox.selectForeground", "#002")
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Hud.TCombobox", fieldbackground=PANEL, background=PANEL,
                     foreground=CYAN, arrowcolor=CYAN, bordercolor=CYAN_DK,
                     lightcolor=CYAN_DK, darkcolor=CYAN_DK, selectbackground=PANEL,
                     selectforeground=CYAN)
        st.configure("Hud.TEntry", fieldbackground=PANEL, foreground=CYAN,
                     bordercolor=CYAN_DK, lightcolor=CYAN_DK, darkcolor=CYAN_DK,
                     insertcolor=CYAN)

    # ---- static sci-fi chrome ----
    def _draw_chrome(self):
        c = self.c
        # outer frame (double stroke = faux glow)
        c.create_polygon(*bevel(10, 10, W - 10, H - 10, 22), outline=CYAN_DK,
                         fill="", width=5)
        c.create_polygon(*bevel(10, 10, W - 10, H - 10, 22), outline=CYAN,
                         fill="", width=2)
        # header bar
        c.create_polygon(*bevel(26, 24, W - 26, 74, 14), outline=CYAN, fill=HEADER, width=2)
        c.create_text(44, 40, anchor="w", text="DUODESK", fill=CYAN,
                      font=(MONO, 24, "bold"))
        c.create_text(46, 62, anchor="w",
                      text="KEYBOARD  ·  MOUSE  ·  CLIPBOARD   //   2 SYSTEMS",
                      fill=MUTED, font=(MONO, 9, "bold"))
        # corner hatch decorations
        self._hatch(W - 92, 30, +1)
        self._hatch(44, H - 40, -1)
        # little nodes
        for (nx, ny) in ((28, 150), (W - 28, 150), (28, 470), (W - 28, 470)):
            c.create_oval(nx - 3, ny - 3, nx + 3, ny + 3, outline=CYAN, fill=BG, width=2)

        c.create_text(40, 100, anchor="w", text="// SELECT ROLE", fill=MUTED,
                      font=(MONO, 10, "bold"))
        # divider under the radios
        c.create_line(34, 184, W - 34, 184, fill=CYAN_DK, width=1)

    def _hatch(self, x, y, d):
        for i in range(4):
            self.c.create_line(x + i * 9, y, x + i * 9 + 14 * d, y + 16,
                               fill=CYAN_DK, width=2)

    # ---- interactive widgets placed on the canvas ----
    def _build_widgets(self):
        c = self.c

        def radio(y, text, val):
            rb = tk.Radiobutton(c, text=text, variable=self.mode, value=val,
                                command=self._sync, bg=BG, fg=TEXT, selectcolor=PANEL,
                                activebackground=BG, activeforeground=CYAN, bd=0,
                                highlightthickness=0, font=(MONO, 12, "bold"),
                                anchor="w")
            c.create_window(36, y, anchor="w", window=rb)

        radio(130, "CONTROL THE OTHER SYSTEM   [ SERVER ]", "server")
        radio(160, "BE CONTROLLED BY THE OTHER  [ CLIENT ]", "client")

        # server panel
        self.srv = tk.Frame(c, bg=BG)
        tk.Label(self.srv, text="OTHER SYSTEM IS ON MY", bg=BG, fg=TEXT,
                 font=(MONO, 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Combobox(self.srv, textvariable=self.edge, values=["right", "left"],
                     width=7, state="readonly", style="Hud.TCombobox").grid(
            row=0, column=1, padx=8)
        tk.Label(self.srv, text="CLIENT CONNECTS TO THIS IP:", bg=BG, fg=MUTED,
                 font=(MONO, 10, "bold")).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        tk.Label(self.srv, text=lan_ip(), bg=BG, fg=GREEN,
                 font=(MONO, 15, "bold")).grid(row=2, column=0, columnspan=2, sticky="w")
        self.srv_win = c.create_window(36, 210, anchor="nw", window=self.srv)

        # client panel
        self.cli = tk.Frame(c, bg=BG)
        tk.Label(self.cli, text="SERVER IP ADDRESS", bg=BG, fg=TEXT,
                 font=(MONO, 11, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Entry(self.cli, textvariable=self.host, width=22, style="Hud.TEntry",
                  font=(MONO, 13)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.cli_win = c.create_window(36, 210, anchor="nw", window=self.cli)

        # speed + port
        opts = tk.Frame(c, bg=BG)
        tk.Label(opts, text="SPEED", bg=BG, fg=TEXT, font=(MONO, 11, "bold")).grid(row=0, column=0)
        ttk.Combobox(opts, textvariable=self.speed, values=["0.25", "0.35", "0.5", "0.75", "1.0"],
                     width=6, style="Hud.TCombobox").grid(row=0, column=1, padx=(8, 22))
        tk.Label(opts, text="PORT", bg=BG, fg=TEXT, font=(MONO, 11, "bold")).grid(row=0, column=2)
        ttk.Entry(opts, textvariable=self.port, width=8, style="Hud.TEntry",
                  font=(MONO, 12)).grid(row=0, column=3, padx=8)
        c.create_window(36, 300, anchor="nw", window=opts)

        # status line
        self.status_item = c.create_text(44, 438, anchor="w", text="IDLE",
                                         fill=MUTED, font=(MONO, 11, "bold"))
        self.dot = c.create_oval(34, 433, 42, 441, outline=MUTED, fill=MUTED)

        # log
        self.logbox = tk.Text(c, height=6, width=50, state="disabled", relief="flat",
                              bg=PANEL, fg=TEXT, font=(MONO, 10), wrap="word",
                              highlightthickness=1, highlightbackground=CYAN_DK,
                              insertbackground=CYAN, padx=8, pady=6)
        c.create_window(W // 2, 530, window=self.logbox)

    # ---- the START/STOP button (drawn, clickable) ----
    def _draw_button(self):
        c = self.c
        c.delete("btn")
        on = self.running
        line = RED if on else CYAN
        fill = "#3a1414" if on else GLOW
        label = "STOP" if on else "START"
        pts = bevel(36, 350, W - 36, 404, 16)
        c.create_polygon(*pts, outline=line, fill=fill, width=2, tags=("btn", "btnhit"))
        c.create_text(W // 2, 377, text=label, fill=line, font=(MONO, 17, "bold"),
                      tags=("btn", "btnhit"))
        c.tag_bind("btnhit", "<Button-1>", lambda e: self.toggle())
        c.tag_raise("btn")

    # ---- ui helpers ----
    def _sync(self):
        show, hide = (self.srv_win, self.cli_win) if self.mode.get() == "server" \
            else (self.cli_win, self.srv_win)
        self.c.itemconfigure(show, state="normal")
        self.c.itemconfigure(hide, state="hidden")

    def log(self, msg):
        self.root.after(0, self._append, msg)

    def _append(self, msg):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def set_status(self, text, color=MUTED):
        def apply():
            self.c.itemconfigure(self.status_item, text=text.upper(), fill=color)
            self.c.itemconfigure(self.dot, outline=color, fill=color)
        self.root.after(0, apply)

    # ---- start / stop ----
    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self):
        try:
            port = int(self.port.get())
            speed = float(self.speed.get())
        except ValueError:
            self.log("Port and speed must be numbers.")
            return
        if self.mode.get() == "client" and not self.host.get().strip():
            self.log("Enter the server IP address first.")
            return
        self.running = True
        self._draw_button()
        target = self._run_server if self.mode.get() == "server" else self._run_client
        self.worker = threading.Thread(target=target, args=(port, speed), daemon=True)
        self.worker.start()

    def stop(self):
        self.running = False
        self.set_status("Stopping", AMBER)
        if self.instance:
            try:
                self.instance.stop()
            except Exception:
                pass
        if self.server_sock:
            try:
                self.server_sock.close()
            except OSError:
                pass
            self.server_sock = None

    def _finished(self):
        self.running = False
        self.instance = None
        self.root.after(0, self._draw_button)
        self.set_status("Idle", MUTED)

    # ---- workers (background thread) ----
    def _run_server(self, port, speed):
        from .server import Server

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.listen(1)
            self.server_sock = s
            self.set_status(f"Waiting on port {port}", CYAN)
            self.log(f"Ready. On the other computer, connect to {lan_ip()}")
            while self.running:
                try:
                    conn_sock, addr = s.accept()
                except OSError:
                    break
                conn_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.set_status(f"Linked · {addr[0]}", GREEN)
                self.log(f"Client connected: {addr[0]}")
                self.instance = Server(Connection(conn_sock), edge=self.edge.get(), speed=speed)
                self.instance.run()
                self.instance = None
                if self.running:
                    self.set_status(f"Waiting on port {port}", CYAN)
                    self.log("Client disconnected. Waiting again...")
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            self._finished()

    def _run_client(self, port, speed):
        from .client import Client

        host = self.host.get().strip()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.set_status(f"Linked · {host}", GREEN)
            self.log(f"Connected to {host}:{port}. Push the mouse to the shared edge.")
            self.instance = Client(Connection(sock), speed=speed)
            self.instance.run()
            self.log("Connection closed.")
        except Exception as e:
            self.log(f"Could not connect: {e}")
        finally:
            self._finished()

    def _on_close(self):
        self.stop()
        self.root.after(150, self.root.destroy)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
