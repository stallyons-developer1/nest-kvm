"""A small, tidy tkinter front-end so DuoDesk can be run without the terminal.

Pick a mode, set one or two fields, press the button. The server/client runs on
a background thread; the window stays responsive and shows a short status log.
"""

import socket
import threading
import tkinter as tk
from tkinter import ttk

from .protocol import Connection

PORT_DEFAULT = 24800

# palette
BG = "#eef1f6"
CARD = "#ffffff"
ACCENT = "#2563eb"
ACCENT_DK = "#1d4ed8"
GREEN = "#16a34a"
GREEN_DK = "#15803d"
RED = "#dc2626"
RED_DK = "#b91c1c"
TEXT = "#1f2933"
MUTED = "#6b7280"
LINE = "#d8dee9"


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class App:
    def __init__(self, root):
        self.root = root
        root.title("DuoDesk")
        root.configure(bg=BG)
        root.resizable(False, False)

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
        self._build()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._sync()

    # ---- styling ----
    def _init_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=CARD, foreground=TEXT, font=("Helvetica", 12))
        st.configure("Card.TFrame", background=CARD)
        st.configure("Card.TLabel", background=CARD, foreground=TEXT)
        st.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Helvetica", 11))
        st.configure("IP.TLabel", background=CARD, foreground=GREEN_DK, font=("Helvetica", 12, "bold"))
        st.configure("TRadiobutton", background=CARD, foreground=TEXT)
        st.map("TRadiobutton", background=[("active", CARD)])
        st.configure("TCombobox", fieldbackground="white", background="white")
        st.configure("TEntry", fieldbackground="white")
        for name, base, active in (("Start", GREEN, GREEN_DK), ("Stop", RED, RED_DK)):
            st.configure(f"{name}.TButton", background=base, foreground="white",
                         font=("Helvetica", 14, "bold"), padding=12, borderwidth=0,
                         focuscolor=base)
            st.map(f"{name}.TButton", background=[("active", active), ("pressed", active)],
                   foreground=[("disabled", "#e5e7eb")])

    # ---- layout ----
    def _build(self):
        # header band
        header = tk.Frame(self.root, bg=ACCENT, height=70)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        tk.Label(header, text="DuoDesk", bg=ACCENT, fg="white",
                 font=("Helvetica", 22, "bold")).place(x=20, y=10)
        tk.Label(header, text="one keyboard · mouse · clipboard  —  two computers",
                 bg=ACCENT, fg="#dbe4ff", font=("Helvetica", 11)).place(x=22, y=44)

        card = ttk.Frame(self.root, style="Card.TFrame", padding=18)
        card.grid(row=1, column=0, sticky="nsew")

        # mode
        ttk.Label(card, text="What should this computer do?", style="Muted.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(card, text="Control the other computer  (server)",
                        variable=self.mode, value="server", command=self._sync).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Radiobutton(card, text="Be controlled by the other  (client)",
                        variable=self.mode, value="client", command=self._sync).grid(
            row=2, column=0, columnspan=2, sticky="w")

        ttk.Separator(card).grid(row=3, column=0, columnspan=2, sticky="ew", pady=12)

        # server-only
        self.srv = ttk.Frame(card, style="Card.TFrame")
        self.srv.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Label(self.srv, text="The other computer is on my", style="Card.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Combobox(self.srv, textvariable=self.edge, values=["right", "left"],
                     width=7, state="readonly").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(self.srv, text=f"On the client, connect to this IP:", style="Muted.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(self.srv, text=lan_ip(), style="IP.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w")

        # client-only
        self.cli = ttk.Frame(card, style="Card.TFrame")
        self.cli.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Label(self.cli, text="Server IP address", style="Card.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Entry(self.cli, textvariable=self.host, width=20, font=("Helvetica", 13)).grid(
            row=1, column=0, sticky="w", pady=(4, 0))

        # shared options
        opts = ttk.Frame(card, style="Card.TFrame")
        opts.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Label(opts, text="Mouse speed", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opts, textvariable=self.speed, values=["0.25", "0.35", "0.5", "0.75", "1.0"],
                     width=6).grid(row=0, column=1, sticky="w", padx=(8, 20))
        ttk.Label(opts, text="Port", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(opts, textvariable=self.port, width=8).grid(row=0, column=3, sticky="w", padx=8)

        # action button
        self.btn = ttk.Button(card, text="Start", style="Start.TButton", command=self.toggle)
        self.btn.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(18, 10))

        # status
        self.dot = tk.Label(card, text="●", bg=CARD, fg=MUTED, font=("Helvetica", 12))
        self.dot.grid(row=7, column=0, sticky="w")
        self.status = ttk.Label(card, text="Idle", style="Muted.TLabel")
        self.status.grid(row=7, column=0, sticky="w", padx=(18, 0))

        # log
        self.logbox = tk.Text(card, height=7, width=48, state="disabled", relief="flat",
                              bg="#f3f5f9", fg=TEXT, font=("Menlo", 10), wrap="word",
                              highlightthickness=1, highlightbackground=LINE, padx=8, pady=6)
        self.logbox.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        card.columnconfigure(0, weight=1)

    # ---- ui helpers ----
    def _sync(self):
        if self.mode.get() == "server":
            self.srv.grid()
            self.cli.grid_remove()
        else:
            self.cli.grid()
            self.srv.grid_remove()

    def log(self, msg):
        self.root.after(0, self._append, msg)

    def _append(self, msg):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def set_status(self, text, color=MUTED):
        def apply():
            self.status.configure(text=text)
            self.dot.configure(fg=color)
        self.root.after(0, apply)

    # ---- start / stop ----
    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

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
        self.btn.configure(text="Stop", style="Stop.TButton")
        target = self._run_server if self.mode.get() == "server" else self._run_client
        self.worker = threading.Thread(target=target, args=(port, speed), daemon=True)
        self.worker.start()

    def stop(self):
        self.running = False
        self.set_status("Stopping...", "#d97706")
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
        self.root.after(0, lambda: self.btn.configure(text="Start", style="Start.TButton"))
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
            self.set_status(f"Waiting for the client on port {port}", ACCENT)
            self.log(f"Ready. On the other computer, connect to {lan_ip()}")
            while self.running:
                try:
                    conn_sock, addr = s.accept()
                except OSError:
                    break
                conn_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.set_status(f"Connected to {addr[0]}", GREEN)
                self.log(f"Client connected: {addr[0]}")
                self.instance = Server(Connection(conn_sock), edge=self.edge.get(), speed=speed)
                self.instance.run()
                self.instance = None
                if self.running:
                    self.set_status(f"Waiting for the client on port {port}", ACCENT)
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
            self.set_status(f"Connected to {host}", GREEN)
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
