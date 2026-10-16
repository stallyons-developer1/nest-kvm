"""HTML/CSS front-end (sci-fi HUD) rendered in a native webview via pywebview.

The page (ui.html) calls these Api methods through `window.pywebview.api.*`; this
class pushes status/log back into the page with `window.evaluate_js(...)`. The
server/client run on a background thread exactly like the terminal commands.
"""

import json
import os
import socket
import threading

from .protocol import Connection


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class Api:
    def __init__(self):
        self.window = None
        self.running = False
        self.server_sock = None
        self.instance = None

    # ---- called from JS ----
    def get_ip(self):
        return lan_ip()

    def start(self, payload):
        if self.running:
            return
        try:
            port = int(payload.get("port", 24800))
            speed = float(payload.get("speed", 0.5))
        except (ValueError, TypeError):
            self._log("Port and speed must be numbers.")
            return
        mode = payload.get("mode", "server")
        host = (payload.get("host") or "").strip()
        edge = payload.get("edge", "right")
        if mode == "client" and not host:
            self._log("Enter the server IP address first.")
            return
        self.running = True
        self._js("window.duodesk.running(true)")
        target = self._run_server if mode == "server" else self._run_client
        threading.Thread(target=target, args=(edge, host, port, speed), daemon=True).start()

    def close(self):
        self.stop()
        try:
            self.window.destroy()
        except Exception:
            pass

    def stop(self):
        self.running = False
        self._status("Stopping", "amber")
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

    # ---- push to JS ----
    def _js(self, code):
        w = self.window
        if w:
            try:
                w.evaluate_js(code)
            except Exception:
                pass

    def _log(self, msg):
        self._js(f"window.duodesk.log({json.dumps(str(msg))})")

    def _status(self, text, color):
        self._js(f"window.duodesk.status({json.dumps(text)},{json.dumps(color)})")

    def _finished(self):
        self.running = False
        self.instance = None
        self._js("window.duodesk.running(false)")
        self._status("Idle", "muted")

    # ---- workers ----
    def _run_server(self, edge, host, port, speed):
        from .server import Server

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.listen(1)
            self.server_sock = s
            self._status(f"Waiting on port {port}", "cyan")
            self._log(f"Ready. On the other computer, connect to {lan_ip()}")
            while self.running:
                try:
                    cs, addr = s.accept()
                except OSError:
                    break
                cs.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._status(f"Linked · {addr[0]}", "green")
                self._log(f"Client connected: {addr[0]}")
                self.instance = Server(Connection(cs), edge=edge, speed=speed)
                self.instance.run()
                self.instance = None
                if self.running:
                    self._status(f"Waiting on port {port}", "cyan")
                    self._log("Client disconnected. Waiting again...")
        except Exception as e:
            self._log(f"Error: {e}")
        finally:
            self._finished()

    def _run_client(self, edge, host, port, speed):
        from .client import Client

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._status(f"Linked · {host}", "green")
            self._log(f"Connected to {host}:{port}. Push the mouse to the shared edge.")
            self.instance = Client(Connection(sock), speed=speed)
            self.instance.run()
            self._log("Connection closed.")
        except Exception as e:
            self._log(f"Could not connect: {e}")
        finally:
            self._finished()


def main():
    import webview

    api = Api()
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")
    window = webview.create_window(
        "DuoDesk", url=html_path, js_api=api,
        width=560, height=702, resizable=False, frameless=True,
        easy_drag=True, background_color="#06201f")
    api.window = window

    def _on_loaded():
        api._js(f"window.duodesk.setip({json.dumps(lan_ip())})")

    try:
        window.events.loaded += _on_loaded
    except Exception:
        pass
    try:
        window.events.closing += api.stop
    except Exception:
        pass
    webview.start()
