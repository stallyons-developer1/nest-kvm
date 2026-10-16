"""A tiny tkinter front-end so nest-kvm can be run without the terminal.

Pick a mode, set one or two fields, press the button. The server/client runs on
a background thread; the window stays responsive and shows a short status log.
"""

import socket
import threading
import tkinter as tk
from tkinter import ttk

from .protocol import Connection

PORT_DEFAULT = 24800


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
        root.title("NestKVM")
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

        pad = {"padx": 12, "pady": 4}
        ttk.Label(root, text="NestKVM", font=("", 18, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(12, 2))
        ttk.Label(root, text="Share one keyboard, mouse & clipboard between two computers").grid(
            row=1, column=0, columnspan=2, padx=12)

        box = ttk.LabelFrame(root, text="Mode")
        box.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Radiobutton(box, text="Use THIS computer to control the other  (server)",
                        variable=self.mode, value="server", command=self._sync).pack(anchor="w", padx=8, pady=2)
        ttk.Radiobutton(box, text="Let the other computer control THIS one  (client)",
                        variable=self.mode, value="client", command=self._sync).pack(anchor="w", padx=8, pady=2)

        # server-only: which side + this machine's IP
        self.srv = ttk.Frame(root)
        self.srv.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(self.srv, text="The other computer is on my:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(self.srv, textvariable=self.edge, values=["right", "left"],
                     width=8, state="readonly").grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(self.srv, text=f"Tell the client this IP:  {lan_ip()}",
                  foreground="#2a7").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # client-only: server IP
        self.cli = ttk.Frame(root)
        self.cli.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(self.cli, text="Server IP address:").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.cli, textvariable=self.host, width=18).grid(row=0, column=1, sticky="w", padx=6)

        # shared: speed + port
        opts = ttk.Frame(root)
        opts.grid(row=5, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(opts, text="Mouse speed:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opts, textvariable=self.speed, values=["0.25", "0.35", "0.5", "0.75", "1.0"],
                     width=6).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(opts, text="Port:").grid(row=0, column=2, sticky="w", padx=(16, 0))
        ttk.Entry(opts, textvariable=self.port, width=8).grid(row=0, column=3, sticky="w", padx=6)

        self.btn = ttk.Button(root, text="Start", command=self.toggle)
        self.btn.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=(6, 2))

        self.status = ttk.Label(root, text="Idle", foreground="#888")
        self.status.grid(row=7, column=0, columnspan=2, padx=12, sticky="w")

        self.logbox = tk.Text(root, height=8, width=56, state="disabled",
                              font=("Menlo", 10), wrap="word")
        self.logbox.grid(row=8, column=0, columnspan=2, padx=12, pady=(2, 12))

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._sync()

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

    def set_status(self, text, color="#888"):
        self.root.after(0, lambda: self.status.configure(text=text, foreground=color))

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
        self.btn.configure(text="Stop")
        target = self._run_server if self.mode.get() == "server" else self._run_client
        self.worker = threading.Thread(target=target, args=(port, speed), daemon=True)
        self.worker.start()

    def stop(self):
        self.running = False
        self.set_status("Stopping...", "#c83")
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
        self.root.after(0, lambda: self.btn.configure(text="Start"))
        self.set_status("Idle", "#888")

    # ---- workers (background thread) ----
    def _run_server(self, port, speed):
        from .server import Server

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.listen(1)
            self.server_sock = s
            self.set_status(f"Listening on port {port} — waiting for the client", "#2a7")
            self.log(f"Ready. On the other computer, connect to {lan_ip()}")
            while self.running:
                try:
                    conn_sock, addr = s.accept()
                except OSError:
                    break
                conn_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.set_status(f"Connected to {addr[0]}", "#2a7")
                self.log(f"Client connected: {addr[0]}")
                self.instance = Server(Connection(conn_sock), edge=self.edge.get(), speed=speed)
                self.instance.run()
                self.instance = None
                if self.running:
                    self.set_status(f"Listening on port {port} — waiting for the client", "#2a7")
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
            self.set_status(f"Connected to {host}", "#2a7")
            self.log(f"Connected to server {host}:{port}. Push the mouse to the shared edge.")
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
